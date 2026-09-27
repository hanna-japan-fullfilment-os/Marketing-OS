"""Playwright HTML/SVG renderer (campaign-pipeline.md hybrid pipeline, step 7).

Renders a self-contained HTML string (the composited image is inlined as a base64
data URI by templates.py, so there's no filesystem/network dependency at render
time) to a PNG at an exact pixel size. This is what gives the app pixel-exact
typography and layout instead of relying on an image model to draw text.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from dataclasses import dataclass
from typing import Coroutine, TypeVar

from playwright.async_api import Browser, Playwright, async_playwright

_T = TypeVar("_T")

# Build 5 repair (Part 3): a version identity for this renderer's own PRODUCTION
# behavior — the dedicated-thread/Proactor-event-loop bridge (docs/architecture.md
# section 5n), the exact-pixel-size PNG capture, and the text-overflow probe JS
# above — never the compositor's inputs (those are per-slide, already tracked via
# `creative_direction`/`scene_generation`). Bump this when the RENDERER's own
# mechanics change in a way that could make an old benchmark baseline's rendered
# output not directly comparable to a new run's (e.g. a different capture method,
# a changed overflow-detection heuristic) — never on an unrelated bug fix that
# doesn't change what gets measured or how.
RENDERER_VERSION = "1.0.0"

_TEXT_OVERFLOW_PROBE_JS = """
() => {
  const el = document.querySelector('.text-block');
  if (!el) { return { present: false, overflowed: false }; }
  const rect = el.getBoundingClientRect();
  const overflowed = (
    rect.top < 0 || rect.left < 0 ||
    rect.bottom > window.innerHeight || rect.right > window.innerWidth ||
    el.scrollHeight > el.clientHeight + 1
  );
  return { present: true, overflowed, bottom: rect.bottom, viewportHeight: window.innerHeight };
}
"""


@dataclass(frozen=True)
class RenderDiagnostics:
    """Real DOM measurements taken at render time — not a heuristic guess after the
    fact — used by qa.py to check the "text overflow / safe margins" requirement
    (brief section 22) against the actual rendered layout.
    """

    text_block_present: bool
    text_overflowed: bool


class PlaywrightRenderer:
    """Lazily launches a single shared headless Chromium instance and reuses it
    across renders (the launch itself costs roughly a second; each render after that
    is well under 200ms), rather than paying the launch cost per campaign slide.
    Safe to hold as a long-lived singleton for the life of the backend process —
    call `close()` on shutdown.

    Windows note (round 14): Playwright's async API launches Chromium as a real
    OS subprocess, which asyncio can only do on Windows via the Proactor event
    loop. Uvicorn's own graceful-shutdown signal handling (`loop.
    add_signal_handler`), on the other hand, is only supported on Windows by the
    Selector event loop — the two requirements are mutually exclusive on the
    *same* event loop on Windows, and uvicorn sets up its loop first, so calling
    Playwright directly from a coroutine running on uvicorn's own loop raises
    `NotImplementedError` deep inside Playwright's subprocess-launch code the
    first time it's actually exercised on Windows — a failure mode this app's
    own Linux/Mac dev/CI environment can't reproduce (both platforms' default
    event loops support subprocesses fine), which is why it shipped unnoticed
    until real Windows usage hit it running Autopilot's visuals stage. The fix:
    run Chromium and every page operation on a dedicated background thread with
    its own event loop (forced to Proactor on Windows, default elsewhere), and
    bridge each render call onto it via `run_coroutine_threadsafe` — uvicorn's
    own loop never touches Playwright directly, so each side gets the loop type
    it actually needs.
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._thread_start_lock = threading.Lock()

    def _ensure_renderer_thread(self) -> asyncio.AbstractEventLoop:
        """Starts (once) the dedicated thread Playwright actually runs on, and
        returns its event loop. Safe to call from any thread, any number of
        times — guarded so only the first caller pays the startup cost.
        """
        if self._loop is not None:
            return self._loop
        with self._thread_start_lock:
            if self._loop is not None:
                return self._loop
            ready = threading.Event()
            started_loop: dict[str, asyncio.AbstractEventLoop] = {}

            def _run() -> None:
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                started_loop["loop"] = loop
                ready.set()
                loop.run_forever()

            thread = threading.Thread(target=_run, name="playwright-renderer", daemon=True)
            thread.start()
            ready.wait()
            self._thread = thread
            self._loop = started_loop["loop"]
            return self._loop

    async def _run_on_renderer_thread(self, coro: Coroutine[None, None, _T]) -> _T:
        loop = self._ensure_renderer_thread()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return await asyncio.wrap_future(future)

    async def _ensure_browser(self) -> Browser:
        # Only ever awaited from a coroutine already scheduled onto the
        # renderer thread's own loop (see _run_on_renderer_thread) — never
        # directly from uvicorn's loop — so creating/using the lock here is safe.
        if self._browser_lock is None:
            self._browser_lock = asyncio.Lock()
        async with self._browser_lock:
            if self._browser is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch()
            return self._browser

    async def render_png(self, *, html: str, width: int, height: int) -> bytes:
        png, _ = await self.render_png_with_diagnostics(html=html, width=width, height=height)
        return png

    async def render_png_with_diagnostics(
        self, *, html: str, width: int, height: int
    ) -> tuple[bytes, RenderDiagnostics]:
        return await self._run_on_renderer_thread(self._render(html=html, width=width, height=height))

    async def _render(self, *, html: str, width: int, height: int) -> tuple[bytes, RenderDiagnostics]:
        browser = await self._ensure_browser()
        page = await browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        try:
            await page.set_content(html, wait_until="load")
            probe = await page.evaluate(_TEXT_OVERFLOW_PROBE_JS)
            png = await page.screenshot(type="png")
            diagnostics = RenderDiagnostics(
                text_block_present=bool(probe.get("present", False)),
                text_overflowed=bool(probe.get("overflowed", False)),
            )
            return png, diagnostics
        finally:
            await page.close()

    async def close(self) -> None:
        if self._loop is None:
            return

        async def _shutdown() -> None:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

        await self._run_on_renderer_thread(_shutdown())
        loop, thread = self._loop, self._thread
        self._loop, self._thread = None, None
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=5)


_shared_renderer: PlaywrightRenderer | None = None


def get_renderer() -> PlaywrightRenderer:
    """Process-wide singleton so `app.main`'s lifespan can close one browser on
    shutdown rather than every call site managing its own lifecycle.
    """
    global _shared_renderer
    if _shared_renderer is None:
        _shared_renderer = PlaywrightRenderer()
    return _shared_renderer


async def close_shared_renderer() -> None:
    global _shared_renderer
    if _shared_renderer is not None:
        await _shared_renderer.close()
        _shared_renderer = None
