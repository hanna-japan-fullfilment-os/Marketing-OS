"""Background isolation (campaign-pipeline.md, hybrid creative pipeline step 3).

Isolating the product from its original background is what lets the compositor
place the real, untouched product photo onto a brand-styled background instead of
letting an image model redraw it. This is explicitly marked "optional" in the
pipeline design because a good isolator (rembg) needs a ~176MB model download on
first use — the pipeline must keep working, deterministically, without it.

Everything here operates on Pillow Images already loaded into memory; nothing in
this module opens a path under SOURCE_ASSET_ROOT itself (the caller — pipeline.py —
owns that read, exactly once, in read-only mode).
"""
from __future__ import annotations

from typing import Protocol

from PIL import Image


class BackgroundIsolator(Protocol):
    """Given a product photo, return an RGBA image with the background removed
    (transparent) where possible. Implementations must not mutate the input image.
    """

    def isolate(self, image: Image.Image) -> Image.Image: ...

    @property
    def name(self) -> str: ...


class NoOpBackgroundIsolator:
    """Always available, fully deterministic: returns the image unchanged (converted
    to RGBA so the compositor's alpha-compositing path is uniform regardless of which
    isolator ran). This is the default — the pipeline is fully functional with only
    this isolator, which is why it's never a hard dependency.
    """

    name = "none"

    def isolate(self, image: Image.Image) -> Image.Image:
        return image.convert("RGBA")


class RembgBackgroundIsolator:
    """Wraps the optional `rembg` package. Only imported when this class is
    instantiated, so the rest of the app works with rembg absent. Raises a clear
    RuntimeError (not an import-time crash) if rembg isn't installed, so callers can
    decide to fall back rather than the whole request failing.
    """

    name = "rembg"

    def __init__(self) -> None:
        try:
            from rembg import remove  # noqa: F401  (imported for its side effect of validating install)
        except ImportError as exc:  # pragma: no cover - exercised only when rembg is absent
            raise RuntimeError(
                "rembg is not installed. Install it with `pip install rembg` to enable "
                "background isolation, or continue using NoOpBackgroundIsolator."
            ) from exc
        self._remove = remove

    def isolate(self, image: Image.Image) -> Image.Image:
        result = self._remove(image.convert("RGBA"))
        return result.convert("RGBA")


# BUILD6R_IMMUTABLE_SHA_CUTOUT_V1
class ImmutableProductCutoutIsolator:
    """Create a deterministic transparent product layer from a real source asset.

    Safety properties:

    * The source file is read-only.
    * RGB product artwork is never regenerated or repainted.
    * Only the derived alpha channel is changed.
    * Background removal is border-connected, so internal light/white product
      details are not removed merely because they resemble the background.
    * Results are cached by the exact SHA-256 of the source bytes.
    * Low-confidence photos fail conservatively to the configured fallback.
    """

    ALGORITHM_VERSION = "build6r-immutable-cutout-v1.1"
    THRESHOLD = 30
    FEATHER_RADIUS = 0.65
    # Build 6R empirical calibration:
    # The owner-verified canonical Melano CC studio source produced a clean,
    # human-reviewed threshold-30 cutout with border_match_ratio=0.611760703
    # and removed_pixel_ratio=0.268042046. The former 0.80 gate therefore
    # created a false negative. 0.60 admits that verified clean-background
    # case while the independent removed-area bounds and border-connected
    # algorithm remain mandatory.
    MIN_BORDER_MATCH_RATIO = 0.60
    MIN_REMOVED_RATIO = 0.03
    MAX_REMOVED_RATIO = 0.92

    def __init__(
        self,
        *,
        source_path,
        cache_root=None,
        fallback=None,
    ) -> None:
        from pathlib import Path

        self.source_path = Path(
            source_path
        )

        if cache_root is None:
            cache_root = (
                Path(__file__)
                .resolve()
                .parents[3]
                / "data"
                / "derived-products"
            )

        self.cache_root = Path(
            cache_root
        )

        self.fallback = (
            fallback
            if fallback is not None
            else NoOpBackgroundIsolator()
        )

        self._name = (
            "immutable_sha_cutout"
        )

    @property
    def name(self) -> str:
        return self._name

    @staticmethod
    def _sha256(path) -> str:
        import hashlib

        digest = hashlib.sha256()

        with open(
            path,
            "rb",
        ) as handle:
            while True:
                chunk = handle.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                digest.update(
                    chunk
                )

        return digest.hexdigest()

    @staticmethod
    def _border_samples(
        rgb,
        border: int,
    ):
        width, height = rgb.size
        pixels = rgb.load()

        samples = []

        for y in range(
            border
        ):
            for x in range(
                width
            ):
                samples.append(
                    pixels[x, y]
                )

        for y in range(
            height - border,
            height,
        ):
            for x in range(
                width
            ):
                samples.append(
                    pixels[x, y]
                )

        for x in range(
            border
        ):
            for y in range(
                border,
                height - border,
            ):
                samples.append(
                    pixels[x, y]
                )

        for x in range(
            width - border,
            width,
        ):
            for y in range(
                border,
                height - border,
            ):
                samples.append(
                    pixels[x, y]
                )

        return samples

    @classmethod
    def _background_reference(
        cls,
        rgb,
    ):
        from statistics import median

        border = max(
            2,
            min(
                12,
                min(
                    rgb.size
                )
                // 10,
            ),
        )

        samples = cls._border_samples(
            rgb,
            border,
        )

        reference = tuple(
            int(
                median(
                    pixel[channel]
                    for pixel in samples
                )
            )
            for channel in range(
                3
            )
        )

        return (
            reference,
            samples,
        )

    @classmethod
    def _distance_squared(
        cls,
        pixel,
        reference,
    ):
        return sum(
            (
                int(pixel[index])
                - int(reference[index])
            )
            ** 2
            for index in range(
                3
            )
        )

    @classmethod
    def _make_alpha(
        cls,
        rgb,
    ):
        from collections import deque
        from PIL import Image, ImageFilter

        width, height = rgb.size
        pixels = rgb.load()

        reference, border_samples = (
            cls._background_reference(
                rgb
            )
        )

        threshold_squared = (
            cls.THRESHOLD
            * cls.THRESHOLD
        )

        border_matches = sum(
            1
            for pixel in border_samples
            if (
                cls._distance_squared(
                    pixel,
                    reference,
                )
                <= threshold_squared
            )
        )

        border_match_ratio = (
            border_matches
            / max(
                1,
                len(
                    border_samples
                ),
            )
        )

        count = (
            width
            * height
        )

        candidate = bytearray(
            count
        )

        for y in range(
            height
        ):
            row = (
                y
                * width
            )

            for x in range(
                width
            ):
                if (
                    cls._distance_squared(
                        pixels[x, y],
                        reference,
                    )
                    <= threshold_squared
                ):
                    candidate[
                        row + x
                    ] = 1

        connected = bytearray(
            count
        )

        queue = deque()

        def seed(
            x,
            y,
        ):
            index = (
                y
                * width
                + x
            )

            if (
                candidate[index]
                and not connected[index]
            ):
                connected[
                    index
                ] = 1

                queue.append(
                    (
                        x,
                        y,
                    )
                )

        for x in range(
            width
        ):
            seed(
                x,
                0,
            )

            seed(
                x,
                height - 1,
            )

        for y in range(
            height
        ):
            seed(
                0,
                y,
            )

            seed(
                width - 1,
                y,
            )

        while queue:
            x, y = queue.popleft()

            if x > 0:
                seed(
                    x - 1,
                    y,
                )

            if x + 1 < width:
                seed(
                    x + 1,
                    y,
                )

            if y > 0:
                seed(
                    x,
                    y - 1,
                )

            if y + 1 < height:
                seed(
                    x,
                    y + 1,
                )

        removed = sum(
            1
            for value in connected
            if value
        )

        removed_ratio = (
            removed
            / max(
                1,
                count,
            )
        )

        confident = (
            border_match_ratio
            >= cls.MIN_BORDER_MATCH_RATIO
            and removed_ratio
            >= cls.MIN_REMOVED_RATIO
            and removed_ratio
            <= cls.MAX_REMOVED_RATIO
        )

        alpha_bytes = bytearray(
            count
        )

        for index in range(
            count
        ):
            alpha_bytes[
                index
            ] = (
                0
                if connected[index]
                else 255
            )

        alpha = Image.frombytes(
            "L",
            (
                width,
                height,
            ),
            bytes(
                alpha_bytes
            ),
        )

        if confident:
            alpha = alpha.filter(
                ImageFilter.GaussianBlur(
                    radius=(
                        cls.FEATHER_RADIUS
                    )
                )
            )

        diagnostics = {
            "background_reference_rgb": (
                list(
                    reference
                )
            ),
            "border_match_ratio": (
                border_match_ratio
            ),
            "removed_pixel_ratio": (
                removed_ratio
            ),
            "confident": (
                confident
            ),
        }

        return (
            alpha,
            diagnostics,
        )

    def _cache_paths(
        self,
        source_sha: str,
    ):
        directory = (
            self.cache_root
            / source_sha
        )

        return (
            directory,
            directory
            / "product-rgba.png",
            directory
            / "isolation.json",
        )

    def _load_cache(
        self,
        *,
        source_sha: str,
    ):
        import json
        from PIL import Image

        (
            _directory,
            product_path,
            metadata_path,
        ) = self._cache_paths(
            source_sha
        )

        if not (
            product_path.is_file()
            and metadata_path.is_file()
        ):
            return None

        try:
            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )

            if (
                metadata.get(
                    "source_sha256"
                )
                != source_sha
                or metadata.get(
                    "algorithm_version"
                )
                != self.ALGORITHM_VERSION
                or metadata.get(
                    "threshold"
                )
                != self.THRESHOLD
            ):
                return None

            with Image.open(
                product_path
            ) as cached:
                result = (
                    cached
                    .convert(
                        "RGBA"
                    )
                    .copy()
                )

            self._name = (
                "immutable_sha_cutout_cached"
            )

            return result

        except Exception:
            return None

    def _write_cache(
        self,
        *,
        source_sha: str,
        result,
        metadata: dict,
    ) -> None:
        import json
        import uuid

        (
            directory,
            product_path,
            metadata_path,
        ) = self._cache_paths(
            source_sha
        )

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        product_temp = (
            directory
            / (
                ".product-rgba."
                + uuid.uuid4().hex
                + ".tmp.png"
            )
        )

        metadata_temp = (
            directory
            / (
                ".isolation."
                + uuid.uuid4().hex
                + ".tmp.json"
            )
        )

        try:
            result.save(
                product_temp,
                format="PNG",
            )

            product_temp.replace(
                product_path
            )

            metadata_temp.write_text(
                json.dumps(
                    metadata,
                    indent=2,
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            metadata_temp.replace(
                metadata_path
            )

        finally:
            if product_temp.exists():
                product_temp.unlink()

            if metadata_temp.exists():
                metadata_temp.unlink()

    def isolate(
        self,
        image: Image.Image,
    ) -> Image.Image:
        rgba = image.convert(
            "RGBA"
        )

        source_sha_before = (
            self._sha256(
                self.source_path
            )
        )

        cached = self._load_cache(
            source_sha=source_sha_before
        )

        if cached is not None:
            return cached

        alpha = rgba.getchannel(
            "A"
        )

        alpha_min, alpha_max = (
            alpha.getextrema()
        )

        # Already-transparent source:
        # keep the authentic alpha exactly as supplied.
        if alpha_min < 255:
            result = rgba.copy()

            metadata = {
                "algorithm_version": (
                    self.ALGORITHM_VERSION
                ),
                "source_sha256": (
                    source_sha_before
                ),
                "threshold": (
                    self.THRESHOLD
                ),
                "source_has_transparency": (
                    True
                ),
                "method": (
                    "existing_source_alpha"
                ),
                "confident": (
                    True
                ),
            }

            source_sha_after = (
                self._sha256(
                    self.source_path
                )
            )

            if (
                source_sha_after
                != source_sha_before
            ):
                raise RuntimeError(
                    "Source product changed while "
                    "building immutable product layer."
                )

            self._write_cache(
                source_sha=source_sha_before,
                result=result,
                metadata=metadata,
            )

            self._name = (
                "immutable_existing_alpha"
            )

            return result

        rgb = rgba.convert(
            "RGB"
        )

        (
            generated_alpha,
            diagnostics,
        ) = self._make_alpha(
            rgb
        )

        if not diagnostics[
            "confident"
        ]:
            fallback_result = (
                self.fallback
                .isolate(
                    rgba
                )
            )

            self._name = (
                "immutable_fallback_"
                + self.fallback.name
            )

            return fallback_result

        result = rgba.copy()

        # Only alpha changes.
        # Source RGB artwork remains byte-derived
        # from the authentic image.
        result.putalpha(
            generated_alpha
        )

        source_sha_after = (
            self._sha256(
                self.source_path
            )
        )

        if (
            source_sha_after
            != source_sha_before
        ):
            raise RuntimeError(
                "Source product changed while "
                "building immutable product layer."
            )

        metadata = {
            "algorithm_version": (
                self.ALGORITHM_VERSION
            ),
            "source_sha256": (
                source_sha_before
            ),
            "threshold": (
                self.THRESHOLD
            ),
            "feather_radius": (
                self.FEATHER_RADIUS
            ),
            "source_has_transparency": (
                False
            ),
            "method": (
                "border_connected_background_removal"
            ),
            **diagnostics,
        }

        self._write_cache(
            source_sha=source_sha_before,
            result=result,
            metadata=metadata,
        )

        self._name = (
            "immutable_sha_cutout"
        )

        return result

def get_isolator(
    *,
    enabled: bool,
    source_path=None,
    prefer_immutable: bool = False,
    cache_root=None,
) -> BackgroundIsolator:
    """Resolve the product-background isolation strategy.

    Build 6R immutable-product contract:

    When ``prefer_immutable`` is true and a real source path is available,
    the deterministic SHA-keyed cutout runs first. It changes only the
    derived alpha channel and never regenerates or repaints product artwork.

    ``enabled`` retains its original meaning for legacy/manual callers:
    when true, rembg may be used as the fallback if the conservative
    deterministic cutout cannot establish a safe background mask.
    """

    fallback: BackgroundIsolator = (
        NoOpBackgroundIsolator()
    )

    if enabled:
        try:
            fallback = (
                RembgBackgroundIsolator()
            )
        except RuntimeError:
            fallback = (
                NoOpBackgroundIsolator()
            )

    if (
        prefer_immutable
        and source_path is not None
    ):
        return (
            ImmutableProductCutoutIsolator(
                source_path=source_path,
                cache_root=cache_root,
                fallback=fallback,
            )
        )

    return fallback

