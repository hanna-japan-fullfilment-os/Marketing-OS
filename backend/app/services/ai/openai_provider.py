"""OpenAI implementation of AIProvider / ResearchProvider / ImageProvider.

This is the ONLY module allowed to import the `openai` SDK. Model names are always
passed in by the caller (which reads them from Settings/config) — never hardcoded
here, per the brief's "model names live in configuration" rule.
"""
from __future__ import annotations

import base64
import math
import hashlib
import json
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import TypeVar

from openai import AsyncOpenAI

# Build 6R runtime safety: never inherit the SDK's long request
# timeout or implicit retry policy for governed paid execution.
_OPENAI_REQUEST_TIMEOUT_SECONDS = 180.0
_OPENAI_MAX_RETRIES = 0
from pydantic import BaseModel

from ...schemas.ai import (
    BrandVisualStyleAnalysis, OpportunityDiscoveryResult, ProductFidelityCheck, ProductZoneDetection,
    ResearchQuery, ResearchResult, SourceProductIdentityCheck,
)
from ...schemas.qa import CreativeCritiqueResult
import io
from PIL import Image

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# --- Build 6 (Production Integration) — real-usage cost estimation ----------
# Approximate published per-1M-token pricing (USD) as of when this was written
# — NOT fetched live, and never claimed to be exact to the cent (a provider's
# published price list changes over time; this app's own job is honest
# best-effort, not real-time billing reconciliation). An unrecognized model
# name (e.g. a future model this table hasn't been updated for) simply prices
# at $0 for that call rather than guessing — the token COUNTS themselves
# (always real, straight from the API response) are what carry_forward
# requirement 6 actually cares about most; a $0 estimated_cost_usd next to
# real token counts is still honest, non-fabricated data.
_TEXT_PRICING_USD_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    # model: (input $/1M tokens, output $/1M tokens)
    "gpt-5.1": (1.25, 10.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}
# Approximate published per-image pricing (USD), by quality tier — gpt-image-1
# only; a model/quality combination not listed here prices at $0, same honest-
# fallback reasoning as the text table above.
_IMAGE_PRICING_USD_PER_IMAGE: dict[str, dict[str, float]] = {
    "gpt-image-1": {"low": 0.011, "medium": 0.042, "high": 0.167, "auto": 0.042},
}


def _text_usage_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _TEXT_PRICING_USD_PER_1M_TOKENS.get(model)
    if rates is None:
        return 0.0
    in_rate, out_rate = rates
    return round((input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate, 6)


def _image_usage_cost(model: str, quality: str, count: int) -> float:
    per_image = _IMAGE_PRICING_USD_PER_IMAGE.get(model, {}).get(quality, 0.0)
    return round(per_image * count, 6)

# GPT Image 2.5 is token-priced. Marketing OS must not invent a fixed
# per-image dollar price for these models.
_GPT_IMAGE_2_5_MODELS = {
    "gpt-image-2.5-flare-2026-09-08",
    "gpt-image-2.5-sunburst-2026-09-08",
}

_GPT_IMAGE_2_5_QUALITIES = {
    "low",
    "high",
    "xhigh",
}

_GPT_IMAGE_2_5_SIZES = {
    "1024x1024",
    "1024x1536",
    "1536x1024",
    "1088x1360",
}


def _is_gpt_image_2_5(
    model: str,
) -> bool:
    return (
        model
        in _GPT_IMAGE_2_5_MODELS
    )



_OPENAI_IMAGE_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


def _normalize_openai_image_bytes(
    path: Path,
) -> tuple[bytes, str, str]:
    """Normalize local image bytes for OpenAI image inputs.

    Filename extensions are deliberately not trusted. A file may be
    AVIF/WebP/etc. even when its name ends in .png or .jpg.

    Supported decoded formats are passed through unchanged.
    Unsupported decoded formats such as AVIF are converted in memory
    to PNG before they cross the OpenAI API boundary.
    """

    raw = path.read_bytes()

    try:
        with Image.open(
            io.BytesIO(raw)
        ) as image:
            detected_format = (
                (image.format or "")
                .upper()
            )

            mime = (
                _OPENAI_IMAGE_MIME_BY_FORMAT.get(
                    detected_format
                )
            )

            if mime is not None:
                extension = (
                    "jpg"
                    if detected_format == "JPEG"
                    else detected_format.lower()
                )

                return (
                    raw,
                    mime,
                    extension,
                )

            image.seek(0)

            bands = image.getbands()

            has_alpha = (
                "A" in bands
                or (
                    image.mode == "P"
                    and "transparency"
                    in image.info
                )
            )

            converted = image.convert(
                "RGBA"
                if has_alpha
                else "RGB"
            )

            output = io.BytesIO()

            converted.save(
                output,
                format="PNG",
            )

            payload = (
                output.getvalue()
            )

            return (
                payload,
                "image/png",
                "png",
            )

    except Exception as exc:
        raise ValueError(
            "Unable to decode image "
            f"{path}: {exc}"
        ) from exc


def _openai_image_data_uri(
    path: Path,
) -> str:
    payload, mime, _extension = (
        _normalize_openai_image_bytes(
            path
        )
    )

    encoded = base64.b64encode(
        payload
    ).decode(
        "ascii"
    )

    return (
        f"data:{mime};base64,"
        f"{encoded}"
    )


def _openai_image_upload(
    path: Path,
):
    payload, _mime, extension = (
        _normalize_openai_image_bytes(
            path
        )
    )

    stream = io.BytesIO(
        payload
    )

    # OpenAI's multipart client expects a filename-like attribute.
    stream.name = (
        f"{path.stem}.{extension}"
    )

    return stream




class HardBudgetExceededError(RuntimeError):
    """Fail-closed pre-call Marketing OS budget boundary."""


_HARD_BUDGET_MAX_OUTPUT_TOKENS = 4096
_HARD_BUDGET_INPUT_OVERHEAD_TOKENS = 12000
_HARD_BUDGET_VISION_IMAGE_TOKENS = 20000
_HARD_BUDGET_WEB_SEARCH_RESERVE_USD = 0.10

# Versioned guard inputs, checked against official documentation on 2026-10-23.
# Direct Images edits receive no cached-input discount. Rates alone are NOT
# a billable-token maximum; Sunburst remains blocked until that is established.
_ACCEPTANCE_PRICING = {
    "version": "2026-10-23",
    "text_source": "https://developers.openai.com/api/docs/models/gpt-5.1",
    "image_source": "https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst",
    "gpt-5.1": {"input": "1.25", "output": "10", "context": 400000},
    "gpt-image-2.5-sunburst-2026-09-08": {
        "text_input": "5", "image_input": "8", "image_output": "30",
        "maximum_billable_tokens": None,
    },
}


def _response_has_image(value) -> bool:
    if isinstance(value, dict):
        return value.get("type") == "input_image" or any(
            _response_has_image(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_response_has_image(item) for item in value)
    return False


def _acceptance_text_reservation(model: str) -> float:
    # Reserve the entire documented context window rather than relying on a
    # guessed vision-token count or omitting structured-output schema overhead.
    pricing = _ACCEPTANCE_PRICING.get(model)
    if model != "gpt-5.1" or not isinstance(pricing, dict):
        raise HardBudgetExceededError("HARD_BUDGET_MISSING_PRICING: " + model)
    try:
        if (_ACCEPTANCE_PRICING.get("version") != "2026-10-23"
                or _ACCEPTANCE_PRICING.get("text_source") != "https://developers.openai.com/api/docs/models/gpt-5.1"
                or pricing.get("context") != 400000):
            raise ValueError("missing or unsupported pricing authority/context")
        input_rate = Decimal(pricing["input"])
        output_rate = Decimal(pricing["output"])
        if not all(rate.is_finite() and rate > 0 for rate in (input_rate, output_rate)):
            raise ValueError("invalid rates")
        amount = (Decimal(pricing["context"]) * input_rate
                  + Decimal(_HARD_BUDGET_MAX_OUTPUT_TOKENS) * output_rate) / 1000000
        return float(amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING))
    except (KeyError, ValueError, ArithmeticError, TypeError) as exc:
        raise HardBudgetExceededError("HARD_BUDGET_MISSING_PRICING: " + model) from exc


def _sunburst_reservation() -> float:
    raise HardBudgetExceededError(
        "HARD_BUDGET_UNKNOWN_IMAGE_MAXIMUM: official Sunburst rates are known, "
        "but a documented maximum billable token exposure for this Images "
        "request is not established. No provider call was made."
    )


def _hard_budget_input_token_upper_bound(value) -> int:
    """Conservative upper bound used only for pre-call reservation.

    Text uses UTF-8 byte length because a byte-level tokenizer cannot emit
    more text tokens than the number of encoded bytes. Vision payloads are
    counted separately instead of charging the base64 data-URI length.
    """
    if value is None:
        return 0

    if isinstance(value, str):
        return len(
            value.encode(
                "utf-8"
            )
        )

    if isinstance(value, (bytes, bytearray)):
        return len(value)

    if isinstance(value, dict):
        if (
            value.get("type")
            == "input_image"
        ):
            return (
                _HARD_BUDGET_VISION_IMAGE_TOKENS
            )

        return sum(
            _hard_budget_input_token_upper_bound(
                key
            )
            + _hard_budget_input_token_upper_bound(
                item
            )
            for key, item in value.items()
        )

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return sum(
            _hard_budget_input_token_upper_bound(
                item
            )
            for item in value
        )

    return len(
        str(value).encode(
            "utf-8"
        )
    )


def _hard_budget_text_cost_upper_bound(
    *,
    model: str,
    request_kwargs: dict,
) -> float:
    """Price a deliberately conservative bounded text/vision request.

    Uses Marketing OS's canonical text-pricing implementation rather than
    maintaining a second pricing table. Unknown/unpriceable models fail
    closed before the network call.
    """
    from types import SimpleNamespace

    input_tokens = (
        _HARD_BUDGET_INPUT_OVERHEAD_TOKENS
        + _hard_budget_input_token_upper_bound(
            request_kwargs.get(
                "input"
            )
        )
    )

    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=(
            _HARD_BUDGET_MAX_OUTPUT_TOKENS
        ),
        input_tokens_details=SimpleNamespace(
            cached_tokens=0
        ),
        output_tokens_details=SimpleNamespace(
            reasoning_tokens=0
        ),
    )

    response = SimpleNamespace(
        usage=usage
    )

    try:
        estimated = float(
            _text_usage_cost(
                model,
                input_tokens,
                _HARD_BUDGET_MAX_OUTPUT_TOKENS,
            )
        )
    except Exception as exc:
        raise HardBudgetExceededError(
            "HARD_BUDGET_UNPRICEABLE_TEXT_CALL: "
            + repr(exc)
        ) from exc

    tools = (
        request_kwargs.get("tools")
        or []
    )

    has_web_search = any(
        isinstance(tool, dict)
        and tool.get("type")
        == "web_search"
        for tool in tools
    )

    if has_web_search:
        estimated += (
            _HARD_BUDGET_WEB_SEARCH_RESERVE_USD
        )

    if estimated <= 0:
        raise HardBudgetExceededError(
            "HARD_BUDGET_UNPRICEABLE_TEXT_CALL: "
            + str(model)
        )

    return round(
        estimated,
        6,
    )


class _HardBudgetLedger:
    def __init__(
        self,
        limit_usd: float | None,
        *,
        call_limits: dict[str, int] | None = None,
    ):
        if (
            limit_usd is not None
            and (not math.isfinite(limit_usd) or limit_usd <= 0)
        ):
            raise ValueError(
                "hard_budget_usd must be > 0."
            )

        self.limit_usd = (
            float(limit_usd)
            if limit_usd is not None
            else None
        )

        self.spent_usd = 0.0
        self.reserved_usd = 0.0
        self.blocked_call_count = 0
        self.halted = False
        self.call_limits = dict(call_limits) if call_limits is not None else None
        self.call_counts = dict.fromkeys(("image", "text", "vision", "other"), 0)
        if self.call_limits is not None:
            if not self.enabled or set(self.call_limits) != set(self.call_counts):
                raise ValueError("Acceptance requires a dollar ceiling and all four call-class limits.")
            if any(type(n) is not int or n < 0 for n in self.call_limits.values()):
                raise ValueError("Call limits must be nonnegative integers.")

    def count_attempt(self, call_class: str) -> None:
        if self.halted:
            raise HardBudgetExceededError("HARD_BUDGET_HALTED: further calls prohibited.")
        if call_class not in self.call_counts:
            raise HardBudgetExceededError("HARD_BUDGET_UNKNOWN_CALL_CLASS")
        if self.call_limits is not None and self.call_counts[call_class] >= self.call_limits[call_class]:
            raise HardBudgetExceededError("HARD_CALL_CAP_PRECALL_BLOCK: " + call_class)
        self.call_counts[call_class] += 1

    @property
    def enabled(self) -> bool:
        return (
            self.limit_usd is not None
        )

    def reserve(
        self,
        amount_usd: float,
        *,
        operation: str,
    ) -> float:
        amount = float(amount_usd)
        if self.halted or not math.isfinite(amount) or amount <= 0:
            raise HardBudgetExceededError("HARD_BUDGET_INVALID_RESERVATION_OR_HALTED")
        amount = float(Decimal(str(amount)).quantize(Decimal("0.000001"), rounding=ROUND_CEILING))

        if not self.enabled:
            return amount

        projected = (Decimal(str(self.spent_usd)) + Decimal(str(self.reserved_usd))
                     + Decimal(str(amount)))

        if (
            projected
            > Decimal(str(self.limit_usd))
        ):
            self.blocked_call_count += 1

            remaining = max(
                0.0,
                self.limit_usd
                - self.spent_usd
                - self.reserved_usd,
            )

            raise HardBudgetExceededError(
                "HARD_BUDGET_PRECALL_BLOCK: "
                + operation
                + " requires reserved maximum $"
                + f"{amount:.6f}"
                + " but only $"
                + f"{remaining:.6f}"
                + " remains under ceiling $"
                + f"{self.limit_usd:.6f}"
                + ". No API call was made."
            )

        self.reserved_usd = round(
            self.reserved_usd
            + amount,
            6,
        )

        return amount

    def release(
        self,
        reserved_usd: float,
    ) -> None:
        if not self.enabled:
            return

        self.reserved_usd = round(
            max(
                0.0,
                self.reserved_usd
                - float(reserved_usd),
            ),
            6,
        )

    def commit(
        self,
        reserved_usd: float,
        actual_usd: float,
        *,
        operation: str,
    ) -> None:
        if not self.enabled:
            return

        reserved = float(
            reserved_usd
        )

        actual = float(actual_usd)

        if (
            not math.isfinite(actual) or actual < 0 or actual
            > reserved + 1e-9
        ):
            self.halted = True
            raise HardBudgetExceededError(
                "HARD_BUDGET_RESERVATION_BREACH: "
                + operation
                + " actual local-model cost $"
                + f"{actual:.6f}"
                + " exceeded conservative reservation $"
                + f"{reserved:.6f}"
                + ". Further paid calls are prohibited."
            )

        projected = (
            self.spent_usd
            + actual
        )

        if (
            projected
            > self.limit_usd + 1e-9
        ):
            self.halted = True
            raise HardBudgetExceededError(
                "HARD_BUDGET_ACCOUNTING_BREACH: "
                + operation
                + " would raise local-model spend to $"
                + f"{projected:.6f}"
                + " above ceiling $"
                + f"{self.limit_usd:.6f}"
                + "."
            )

        self.release(reserved)
        self.spent_usd = float(Decimal(str(projected)).quantize(
            Decimal("0.000001"), rounding=ROUND_CEILING))

    def snapshot(self) -> dict:
        remaining = None

        if self.enabled:
            remaining = round(
                max(
                    0.0,
                    self.limit_usd
                    - self.spent_usd
                    - self.reserved_usd,
                ),
                6,
            )

        return {
            "call_limits": self.call_limits,
            "call_counts": dict(self.call_counts),
            "halted": self.halted,
            "enabled": self.enabled,
            "limit_usd": self.limit_usd,
            "spent_usd": round(
                self.spent_usd,
                6,
            ),
            "reserved_usd": round(
                self.reserved_usd,
                6,
            ),
            "remaining_usd": remaining,
            "blocked_call_count": (
                self.blocked_call_count
            ),
            "max_output_tokens": (
                _HARD_BUDGET_MAX_OUTPUT_TOKENS
                if self.enabled
                else None
            ),
        }


class _BudgetedResponsesProxy:
    def __init__(
        self,
        target,
        ledger: _HardBudgetLedger,
    ):
        self._target = target
        self._ledger = ledger

    async def _call(
        self,
        method_name: str,
        **kwargs,
    ):
        if not self._ledger.enabled:
            method = getattr(
                self._target,
                method_name,
            )

            return await method(
                **kwargs
            )

        request_kwargs = dict(
            kwargs
        )

        strict = self._ledger.call_limits is not None
        if strict:
            allowed = {"model", "input", "text_format", "max_output_tokens"}
            if set(request_kwargs) - allowed:
                raise HardBudgetExceededError("HARD_BUDGET_UNSUPPORTED_REQUEST_VARIANT")
            output_limit = request_kwargs.get("max_output_tokens", _HARD_BUDGET_MAX_OUTPUT_TOKENS)
            if type(output_limit) is not int or not 0 < output_limit <= _HARD_BUDGET_MAX_OUTPUT_TOKENS:
                raise HardBudgetExceededError("HARD_BUDGET_OUTPUT_LIMIT_REQUIRED")
        elif request_kwargs.get("max_output_tokens", _HARD_BUDGET_MAX_OUTPUT_TOKENS) > _HARD_BUDGET_MAX_OUTPUT_TOKENS:
            raise HardBudgetExceededError("HARD_BUDGET_OUTPUT_LIMIT_REQUIRED")

        request_kwargs.setdefault(
            "max_output_tokens",
            _HARD_BUDGET_MAX_OUTPUT_TOKENS,
        )

        model = str(
            request_kwargs.get(
                "model",
                "",
            )
        )

        reserved = _acceptance_text_reservation(model) if strict else (
            _hard_budget_text_cost_upper_bound(
                model=model,
                request_kwargs=request_kwargs,
            )
        )

        reservation = (
            self._ledger.reserve(
                reserved,
                operation=(
                    "responses."
                    + method_name
                ),
            )
        )

        try:
            self._ledger.count_attempt("vision" if _response_has_image(request_kwargs.get("input")) else "text")
        except HardBudgetExceededError:
            self._ledger.release(reservation)
            raise

        try:
            method = getattr(
                self._target,
                method_name,
            )

            response = await method(
                **request_kwargs
            )

        except BaseException:
            # A timeout/cancellation/error can still be billed. Retain the
            # maximum reservation and consumed attempt, including on retries.
            raise

        try:
            usage = getattr(
                response,
                "usage",
                None,
            )
            if any(type(getattr(usage, key, None)) is not int or getattr(usage, key) < 0
                   for key in ("input_tokens", "output_tokens")):
                return response  # incomplete usage: keep the entire reservation

            actual_input_tokens = (
                int(
                    getattr(
                        usage,
                        "input_tokens",
                        0,
                    )
                    or 0
                )
                if usage is not None
                else 0
            )

            actual_output_tokens = (
                int(
                    getattr(
                        usage,
                        "output_tokens",
                        0,
                    )
                    or 0
                )
                if usage is not None
                else 0
            )

            actual = float(
                _text_usage_cost(
                    model,
                    actual_input_tokens,
                    actual_output_tokens,
                )
            )

            if usage is None or actual <= 0:
                return response  # retain maximum; missing usage never means free

            if strict:
                rates = _ACCEPTANCE_PRICING[model]
                actual = float((Decimal(actual_input_tokens) * Decimal(rates["input"])
                                + Decimal(actual_output_tokens) * Decimal(rates["output"])) / 1000000)

            tools = (
                request_kwargs.get(
                    "tools"
                )
                or []
            )

            if any(
                isinstance(tool, dict)
                and tool.get("type")
                == "web_search"
                for tool in tools
            ):
                actual += (
                    _HARD_BUDGET_WEB_SEARCH_RESERVE_USD
                )

            self._ledger.commit(
                reservation,
                actual,
                operation=(
                    "responses."
                    + method_name
                ),
            )

        except Exception:
            # A breach is sticky and its reservation remains encumbered.
            raise

        return response

    async def parse(
        self,
        **kwargs,
    ):
        return await self._call(
            "parse",
            **kwargs,
        )

    async def create(
        self,
        **kwargs,
    ):
        return await self._call(
            "create",
            **kwargs,
        )

    def __getattr__(
        self,
        name,
    ):
        if self._ledger.call_limits is not None:
            raise HardBudgetExceededError("HARD_BUDGET_UNSUPPORTED_RESPONSES_METHOD: " + name)
        return getattr(
            self._target,
            name,
        )


class _BudgetedImagesProxy:
    def __init__(
        self,
        target,
        ledger: _HardBudgetLedger,
    ):
        self._target = target
        self._ledger = ledger

    async def _call(
        self,
        method_name: str,
        **kwargs,
    ):
        model = str(
            kwargs.get(
                "model",
                "",
            )
        )

        if not self._ledger.enabled:
            method = getattr(
                self._target,
                method_name,
            )

            return await method(
                **kwargs
            )

        token_priced = _is_gpt_image_2_5(model)
        if token_priced:
            estimated = _sunburst_reservation()  # fails before invocation today
        elif self._ledger.call_limits is not None:
            # Legacy fixed-output estimates omit edit input charges. They are
            # not a supported substitute for the configured Sunburst contract.
            raise HardBudgetExceededError("HARD_BUDGET_UNSUPPORTED_IMAGE_PRICING: " + model)

        quality = str(
            kwargs.get(
                "quality",
                "high",
            )
        )

        count = int(
            kwargs.get(
                "n",
                1,
            )
            or 1
        )

        try:
            estimated = estimated if token_priced else float(
                _image_usage_cost(
                    model,
                    quality,
                    count=count,
                )
            )

        except Exception as exc:
            raise HardBudgetExceededError(
                "HARD_BUDGET_UNPRICEABLE_IMAGE_CALL: "
                + repr(exc)
            ) from exc

        if estimated <= 0:
            raise HardBudgetExceededError(
                "HARD_BUDGET_UNPRICEABLE_IMAGE_CALL: "
                + model
                + "/"
                + quality
            )

        reservation = (
            self._ledger.reserve(
                estimated,
                operation=(
                    "images."
                    + method_name
                ),
            )
        )

        try:
            self._ledger.count_attempt("image")
        except HardBudgetExceededError:
            self._ledger.release(reservation)
            raise

        try:
            method = getattr(
                self._target,
                method_name,
            )

            response = await method(
                **kwargs
            )

        except BaseException:
            raise

        if token_priced:
            # Do not infer token usage from dimensions or output byte length.
            usage = getattr(response, "usage", None)
            details = getattr(usage, "input_tokens_details", None)
            counts = [getattr(details, "text_tokens", None),
                      getattr(details, "image_tokens", None),
                      getattr(usage, "output_tokens", None)]
            if any(type(n) is not int or n < 0 for n in counts):
                return response  # retain the full maximum reservation
            rates = _ACCEPTANCE_PRICING.get(model)
            if not rates:
                self._ledger.halted = True
                raise HardBudgetExceededError("HARD_BUDGET_MISSING_PRICING: " + model)
            actual = sum(Decimal(n) * Decimal(rates[key]) for n, key in zip(
                counts, ("text_input", "image_input", "image_output"))) / 1000000
            self._ledger.commit(reservation, float(actual), operation="images." + method_name)
            return response

        self._ledger.commit(
            reservation,
            estimated,
            operation=(
                "images."
                + method_name
            ),
        )

        return response

    async def generate(
        self,
        **kwargs,
    ):
        return await self._call(
            "generate",
            **kwargs,
        )

    async def edit(
        self,
        **kwargs,
    ):
        return await self._call(
            "edit",
            **kwargs,
        )

    def __getattr__(
        self,
        name,
    ):
        if self._ledger.call_limits is not None:
            raise HardBudgetExceededError("HARD_BUDGET_UNSUPPORTED_IMAGES_METHOD: " + name)
        return getattr(
            self._target,
            name,
        )


class _BudgetedOpenAIClient:
    def __init__(
        self,
        target,
        ledger: _HardBudgetLedger,
    ):
        self._target = target
        self._ledger = ledger
        self.responses = (
            _BudgetedResponsesProxy(
                target.responses,
                ledger,
            )
        )
        self.images = (
            _BudgetedImagesProxy(
                target.images,
                ledger,
            )
        )

    def __getattr__(
        self,
        name,
    ):
        if self._ledger.call_limits is not None:
            raise HardBudgetExceededError("HARD_BUDGET_UNSUPPORTED_SDK_RESOURCE: " + name)
        return getattr(
            self._target,
            name,
        )


_BOUNDED_ACCEPTANCE_LIMITS = {"image": 6, "text": 10, "vision": 2, "other": 0}
_SUNBURST_PAYLOAD_LIMITS = {
    "prompt_bytes": 128000, "prompt_characters": 32000,
    "reference_count": 1, "reference_file_bytes": 20 * 1024 * 1024,
    "reference_width": 2048, "reference_height": 2048,
    "reference_pixels": 2048 * 2048,
}


def _actual_bounded_cost(response, model: str, *, image: bool) -> float | None:
    """Uncached Standard usage cost, never a pre-call price guarantee."""
    rates = _ACCEPTANCE_PRICING.get(model)
    if not isinstance(rates, dict):
        raise HardBudgetExceededError("BOUNDED_MISSING_PRICING: " + model)
    usage = getattr(response, "usage", None)
    if image:
        details = getattr(usage, "input_tokens_details", None)
        counts = [getattr(details, "text_tokens", None), getattr(details, "image_tokens", None),
                  getattr(usage, "output_tokens", None)]
        keys = ("text_input", "image_input", "image_output")
    else:
        counts = [getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)]
        keys = ("input", "output")
    if any(type(n) is not int or n < 0 for n in counts):
        return None
    try:
        prices = [Decimal(rates[key]) for key in keys]
        if any(not rate.is_finite() or rate <= 0 for rate in prices):
            raise ValueError("invalid pricing")
        return float(sum(Decimal(n) * rate for n, rate in zip(counts, prices)) / 1000000)
    except (KeyError, ArithmeticError, ValueError) as exc:
        raise HardBudgetExceededError("BOUNDED_MISSING_PRICING: " + model) from exc


class _BoundedExposureLedger(_HardBudgetLedger):
    """Provider-attempt exposure, deliberately NOT a hard USD budget."""

    def __init__(self):
        super().__init__(None)
        self.call_limits = dict(_BOUNDED_ACCEPTANCE_LIMITS)
        self.in_flight = False
        self.entries: list[dict] = []

    def begin(self, kind: str, request: dict) -> dict:
        if self.in_flight:
            raise HardBudgetExceededError("BOUNDED_CONCURRENT_CALL_REJECTED")
        self.count_attempt(kind)
        entry = {"class": kind, "status": "attempted", "actual_cost_usd": None,
                 "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()}
        self.entries.append(entry)
        self.in_flight = True
        return entry

    def snapshot(self) -> dict:
        result = super().snapshot()
        known = [entry["actual_cost_usd"] for entry in self.entries if entry["actual_cost_usd"] is not None]
        result.update(bounded_exposure=True, exact_per_run_usd_ceiling=False,
                      in_flight=self.in_flight, entries=[dict(entry) for entry in self.entries],
                      actual_cost_usd=sum(known) if len(known) == len(self.entries) else None,
                      known_actual_cost_usd=sum(known), actual_usage_complete=len(known) == len(self.entries),
                      payload_limits=dict(_SUNBURST_PAYLOAD_LIMITS),
                      sdk_retries=0, http_retries=0, max_concurrent_paid_calls=1)
        return result


def _bounded_image_request(method: str, kwargs: dict) -> dict:
    allowed = {"model", "image", "prompt", "size", "quality", "n", "output_format", "partial_images", "stream"}
    if method != "edit" or set(kwargs) - allowed:
        raise HardBudgetExceededError("BOUNDED_IMAGE_EDIT_ONLY_NO_FALLBACK")
    expected = {"model": "gpt-image-2.5-sunburst-2026-09-08", "size": "1088x1360", "quality": "xhigh"}
    if any(kwargs.get(key) != value for key, value in expected.items()):
        raise HardBudgetExceededError("BOUNDED_IMAGE_MODEL_SIZE_QUALITY_REQUIRED")
    if (kwargs.get("n", 1) != 1 or kwargs.get("output_format", "png") != "png"
            or kwargs.get("partial_images", 0) != 0 or kwargs.get("stream", False) is not False):
        raise HardBudgetExceededError("BOUNDED_IMAGE_SINGLE_PNG_NO_STREAM")
    prompt = kwargs.get("prompt")
    limits = _SUNBURST_PAYLOAD_LIMITS
    if (not isinstance(prompt, str) or not prompt or len(prompt) > limits["prompt_characters"]
            or len(prompt.encode("utf-8")) > limits["prompt_bytes"]):
        raise HardBudgetExceededError("BOUNDED_PROMPT_PAYLOAD_EXCEEDED")
    images = kwargs.get("image")
    if not isinstance(images, list) or len(images) != limits["reference_count"]:
        raise HardBudgetExceededError("BOUNDED_REFERENCE_COUNT_EXCEEDED")
    image_metadata = []
    for stream in images:
        # Only immutable local uploads already prepared by this adapter; no URL,
        # file-id fetch, or external stream can hide unbounded input exposure.
        if not isinstance(stream, io.BytesIO):
            raise HardBudgetExceededError("BOUNDED_LOCAL_REFERENCE_REQUIRED")
        raw = stream.getvalue()
        if not raw or len(raw) > limits["reference_file_bytes"]:
            raise HardBudgetExceededError("BOUNDED_REFERENCE_FILE_BYTES_EXCEEDED")
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            if (width > limits["reference_width"] or height > limits["reference_height"]
                    or width * height > limits["reference_pixels"] or getattr(image, "n_frames", 1) != 1):
                raise HardBudgetExceededError("BOUNDED_REFERENCE_PIXELS_EXCEEDED")
        image_metadata.append({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                               "width": width, "height": height})
    return {"prompt_bytes": len(prompt.encode("utf-8")), "prompt_characters": len(prompt),
            "reference_images": image_metadata, **expected}


class _BoundedAcceptanceResource:
    def __init__(self, target, ledger, *, image=False):
        self._target, self._ledger, self._image = target, ledger, image

    async def _call(self, method, **kwargs):
        model = kwargs.get("model", "")
        if self._ledger.halted:
            raise HardBudgetExceededError("BOUNDED_HALTED_NO_RETRY_OR_FALLBACK")
        if self._image:
            metadata = _bounded_image_request(method, kwargs)
            # Validate all official rates BEFORE invocation, without pretending
            # that those rates establish a maximum number of image tokens.
            from types import SimpleNamespace
            unit_usage = SimpleNamespace(input_tokens_details=SimpleNamespace(text_tokens=1, image_tokens=1), output_tokens=1)
            _actual_bounded_cost(SimpleNamespace(usage=unit_usage), model, image=True)
            kwargs = {**kwargs, "n": 1, "output_format": "png", "partial_images": 0, "stream": False}
            kind = "image"
        else:
            if method not in {"parse", "create"} or set(kwargs) - {"model", "input", "text_format", "max_output_tokens"}:
                raise HardBudgetExceededError("BOUNDED_UNSUPPORTED_RESPONSES_REQUEST")
            _acceptance_text_reservation(model)  # validates official pricing/model
            output = kwargs.get("max_output_tokens", _HARD_BUDGET_MAX_OUTPUT_TOKENS)
            if type(output) is not int or not 0 < output <= _HARD_BUDGET_MAX_OUTPUT_TOKENS:
                raise HardBudgetExceededError("BOUNDED_OUTPUT_TOKEN_LIMIT")
            kwargs = {**kwargs, "max_output_tokens": output}
            kind = "vision" if _response_has_image(kwargs.get("input")) else "text"
            metadata = {"max_output_tokens": output}
        entry = self._ledger.begin(kind, kwargs)
        entry.update(metadata)
        try:
            response = await getattr(self._target, method)(**kwargs)
            if self._image:
                data = getattr(response, "data", None)
                if not data or len(data) != 1 or not getattr(data[0], "b64_json", None):
                    raise ValueError("Malformed single-image response")
                base64.b64decode(data[0].b64_json, validate=True)
            elif method == "parse" and getattr(response, "output_parsed", None) is None:
                raise ValueError("Malformed structured response")
            entry["actual_cost_usd"] = _actual_bounded_cost(response, model, image=self._image)
            entry["status"] = "completed"
            return response
        except BaseException:
            entry["status"] = "failed_or_incomplete"
            self._ledger.halted = True  # no automatic retry/fallback after ANY failure
            raise
        finally:
            self._ledger.in_flight = False

    async def parse(self, **kwargs):
        if self._image:
            raise HardBudgetExceededError("BOUNDED_UNSUPPORTED_IMAGE_METHOD")
        return await self._call("parse", **kwargs)

    async def create(self, **kwargs):
        if self._image:
            raise HardBudgetExceededError("BOUNDED_UNSUPPORTED_IMAGE_METHOD")
        return await self._call("create", **kwargs)

    async def edit(self, **kwargs):
        if not self._image:
            raise HardBudgetExceededError("BOUNDED_UNSUPPORTED_RESPONSES_METHOD")
        return await self._call("edit", **kwargs)

    async def generate(self, **kwargs):
        raise HardBudgetExceededError("BOUNDED_IMAGE_EDIT_ONLY_NO_FALLBACK")

    def __getattr__(self, name):
        raise HardBudgetExceededError("BOUNDED_UNSUPPORTED_SDK_METHOD: " + name)


class _BoundedAcceptanceClient:
    def __init__(self, target, ledger):
        self.responses = _BoundedAcceptanceResource(target.responses, ledger)
        self.images = _BoundedAcceptanceResource(target.images, ledger, image=True)

    def __getattr__(self, name):
        raise HardBudgetExceededError("BOUNDED_UNSUPPORTED_SDK_RESOURCE: " + name)


class OpenAIProvider:
    """Implements AIProvider, ResearchProvider, and ImageProvider against the OpenAI
    Responses API + Images API.

    Build 6 (Production Integration, carry-forward requirement 6): the ONLY
    place in this app that can know a REAL token/image count, since it's the
    only implementation making a real network call — see `services/
    usage_tracking.py`'s module docstring for the full design. Every method
    below appends one event to `self._usage_events` right after its real API
    call succeeds; `drain_usage_events()` reads and clears that list. A fake
    test provider has no such method/list at all, which is the correct,
    honest "no real usage happened" signal `usage_tracking.
    drain_provider_usage_events` relies on.
    """

    _bounded_acceptance = False

    def __init__(
        self,
        api_key: str | None = None,
        *,
        hard_budget_usd: float | None = None,
        project_id: str | None = None,
        provider_hard_limit_attested: bool = False,
        max_image_calls: int | None = None,
        acceptance_call_limits: dict[str, int] | None = None,
        bounded_acceptance: bool = False,
    ):
        if bounded_acceptance and (hard_budget_usd is not None or acceptance_call_limits not in (None, _BOUNDED_ACCEPTANCE_LIMITS)):
            raise ValueError("Bounded exposure is not an exact USD ceiling; requires fixed 6/10/2/0 limits.")
        self._bounded_acceptance = bounded_acceptance
        if bounded_acceptance:
            import httpx
            bounded_http = httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(retries=0),
                timeout=_OPENAI_REQUEST_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False)
        raw_client = (
            AsyncOpenAI(
                api_key=api_key,
                timeout=_OPENAI_REQUEST_TIMEOUT_SECONDS,
                max_retries=_OPENAI_MAX_RETRIES,
                **({"project": project_id} if bounded_acceptance and project_id else {}),
                **({"http_client": bounded_http} if bounded_acceptance else {}),
            )
            if api_key
            else None
        )

        if (
            max_image_calls is not None
            and max_image_calls <= 0
        ):
            raise ValueError(
                "max_image_calls must be > 0 when configured."
            )

        self._usage_events: list[dict] = []

        self._hard_budget_ledger = (
            _BoundedExposureLedger() if bounded_acceptance else _HardBudgetLedger(
                hard_budget_usd,
                call_limits=acceptance_call_limits,
            )
        )

        self._project_id = (
            str(
                project_id
                or ""
            ).strip()
        )

        self._provider_hard_limit_attested = bool(
            provider_hard_limit_attested
        )

        self._max_image_calls = (
            max_image_calls
        )

        self._image_calls_used = 0

        self._client = (
            _BoundedAcceptanceClient(raw_client, self._hard_budget_ledger)
            if bounded_acceptance and raw_client is not None else _BudgetedOpenAIClient(
                raw_client,
                self._hard_budget_ledger,
            )
            if (
                raw_client is not None
                and self._hard_budget_ledger.enabled
            )
            else raw_client
        )

    def hard_budget_snapshot(self) -> dict:
        snapshot = (
            self._hard_budget_ledger.snapshot()
        )

        snapshot.update(
            {
                "project_id_configured": bool(
                    self._project_id
                ),
                "provider_hard_limit_attested": (
                    self._provider_hard_limit_attested
                ),
                "max_image_calls": (
                    self._max_image_calls
                ),
                "image_calls_used": (
                    self._image_calls_used
                ),
                "image_calls_remaining": (
                    None
                    if self._max_image_calls is None
                    else max(
                        0,
                        self._max_image_calls
                        - self._image_calls_used,
                    )
                ),
            }
        )

        if self._bounded_acceptance:
            used = self._hard_budget_ledger.call_counts["image"]
            snapshot.update(max_image_calls=6, image_calls_used=used, image_calls_remaining=max(0, 6-used))

        return snapshot


    def drain_usage_events(self) -> list[dict]:
        events, self._usage_events = self._usage_events, []
        return events

    def _record_text_usage(
        self,
        response,
        model: str,
        *,
        budget_guard_adjustment_usd: float = 0.0,
    ) -> None:
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
        self._usage_events.append({
            "provider": "openai", "model": model, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "image_count": 0,
            "estimated_cost_usd": _text_usage_cost(model, input_tokens, output_tokens),
            "budget_guard_adjustment_usd": float(budget_guard_adjustment_usd),
        })
        if self._bounded_acceptance:
            actual = _actual_bounded_cost(response, model, image=False)
            self._usage_events[-1].update(actual_cost_usd=actual, cost_known=actual is not None,
                                          estimated_cost_usd=actual if actual is not None else 0.0,
                                          pricing_basis="official_standard_tokens; missing usage remains unknown")

    def _record_image_usage(
        self,
        model: str,
        quality: str,
        count: int = 1,
        *,
        response=None,
    ) -> None:
        cost_known = (
            not _is_gpt_image_2_5(
                model
            )
        )

        estimated_cost = (
            _image_usage_cost(
                model,
                quality,
                count,
            )
            if cost_known
            else 0.0
        )

        self._usage_events.append(
            {
                "provider": "openai",
                "model": model,
                "input_tokens": 0,
                "output_tokens": 0,
                "image_count": count,
                "estimated_cost_usd": estimated_cost,
                "cost_known": cost_known,
                "pricing_basis": (
                    "legacy_fixed_per_image"
                    if cost_known
                    else "provider_project_spend_limit"
                ),
            }
        )
        if self._bounded_acceptance and response is not None:
            actual = _actual_bounded_cost(response, model, image=True)
            usage = getattr(response, "usage", None)
            self._usage_events[-1].update(actual_cost_usd=actual, cost_known=actual is not None,
                                          input_tokens=getattr(usage, "input_tokens", 0) or 0,
                                          output_tokens=getattr(usage, "output_tokens", 0) or 0,
                                          estimated_cost_usd=actual if actual is not None else 0.0,
                                          pricing_basis="official_standard_tokens; no guaranteed pre-call USD maximum")

    def _validate_gpt_image_2_5_call(
        self,
        *,
        model: str,
        quality: str,
        size: str | None,
        count: int = 1,
    ) -> None:
        if self._bounded_acceptance:
            if (model != "gpt-image-2.5-sunburst-2026-09-08" or quality != "xhigh"
                    or size != "1088x1360" or count != 1):
                raise HardBudgetExceededError("BOUNDED_IMAGE_MODEL_SIZE_QUALITY_REQUIRED")
            return  # unified ledger checks immediately before the actual attempt
        if not _is_gpt_image_2_5(
            model
        ):
            return

        if not self._provider_hard_limit_attested:
            raise HardBudgetExceededError(
                "GPT_IMAGE_2_5_PROVIDER_HARD_LIMIT_ATTESTATION_REQUIRED: "
                "no GPT Image 2.5 API call was made."
            )

        if not self._project_id:
            raise HardBudgetExceededError(
                "GPT_IMAGE_2_5_PROJECT_ID_REQUIRED: "
                "no GPT Image 2.5 API call was made."
            )

        if self._max_image_calls is None:
            raise HardBudgetExceededError(
                "GPT_IMAGE_2_5_IMAGE_CALL_LIMIT_REQUIRED: "
                "no GPT Image 2.5 API call was made."
            )

        if model not in _GPT_IMAGE_2_5_MODELS:
            raise HardBudgetExceededError(
                "GPT_IMAGE_2_5_MODEL_NOT_ALLOWED: "
                + model
            )

        if quality not in _GPT_IMAGE_2_5_QUALITIES:
            raise HardBudgetExceededError(
                "GPT_IMAGE_2_5_QUALITY_NOT_ALLOWED: "
                + quality
            )

        if (
            size is not None
            and size not in _GPT_IMAGE_2_5_SIZES
        ):
            raise HardBudgetExceededError(
                "GPT_IMAGE_2_5_SIZE_NOT_ALLOWED: "
                + size
            )

        if count != 1:
            raise HardBudgetExceededError(
                "GPT_IMAGE_2_5_COUNT_NOT_ALLOWED: "
                + str(count)
            )

        projected = (
            self._image_calls_used
            + count
        )

        if projected > self._max_image_calls:
            raise HardBudgetExceededError(
                "GPT_IMAGE_2_5_IMAGE_CALL_LIMIT_EXCEEDED: "
                + str(projected)
                + " > "
                + str(self._max_image_calls)
                + ". No API call was made."
            )

        # Count attempts before the external request. A failed provider
        # request can still consume billable work and must consume allowance.
        self._image_calls_used = (
            projected
        )

    def _require_client(self) -> AsyncOpenAI:
        if self._client is None:
            raise RuntimeError(
                "OpenAI API key is not configured. Set it in Settings before running "
                "research, copy, or image generation."
            )
        return self._client

    # ---- AIProvider -----------------------------------------------------------
    async def generate_structured(
        self, *, system: str, user: str, schema: type[SchemaT], model: str
    ) -> SchemaT:
        client = self._require_client()
        response = await client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=schema,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("Model did not return a structured response matching the requested schema.")
        self._record_text_usage(response, model)
        return parsed

    async def vision_describe(self, *, image_path: Path, prompt: str, model: str) -> str:
        client = self._require_client()
        response = await client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": _openai_image_data_uri(image_path)},
                    ],
                }
            ],
        )
        self._record_text_usage(response, model)
        return response.output_text or ""


    async def analyze_visual_style(
        self, *, image_paths: list[Path], brand_name: str, model: str
    ) -> BrandVisualStyleAnalysis:
        """Shows the model every reference photo in one call (not one `vision_describe`
        call per photo) so it can describe the visual style they establish *together*
        — a shared palette/mood across several photos, not a description of each one
        in isolation. Never invents a style from the brand name alone: at least one
        real image is required by the caller (app/api/brands.py) before this runs.
        """
        client = self._require_client()
        content: list[dict] = [
            {
                "type": "input_text",
                "text": (
                    f"These are real reference/example photos for the brand '{brand_name}' — "
                    "either past marketing the brand liked, or photos of products/scenes that "
                    "capture the look the brand wants. Describe the visual style they establish "
                    "together: dominant colors (as hex codes, best guess is fine), typography "
                    "mood, photography style, and a short list of visual style descriptors. "
                    "Only describe what these images actually show — do not invent details they "
                    "don't support."
                ),
            }
        ]
        for image_path in image_paths:
            content.append(
                {
                    "type": "input_image",
                    "image_url": _openai_image_data_uri(
                        image_path
                    ),
                }
            )

        response = await client.responses.parse(
            model=model,
            input=[{"role": "user", "content": content}],
            text_format=BrandVisualStyleAnalysis,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("Visual style analysis did not return a structured response.")
        self._record_text_usage(response, model)
        return parsed


    async def detect_product_zone(self, *, image_path: Path, model: str) -> ProductZoneDetection:
        """Shows the model the real source photo and asks it to locate the product
        within it — see `ProductZoneDetection` for exactly what's returned and why.
        Never invented from a description; the actual photo bytes are always sent,
        same discipline as `analyze_visual_style` above.
        """
        client = self._require_client()
        response = await client.responses.parse(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "This real product photo will be composited onto a new marketing "
                                "background. Identify the tight bounding box around the actual "
                                "product in the frame — as fractions of the image's width and "
                                "height, top-left origin (crop_left, crop_top, crop_width, "
                                "crop_height) — so cropping to that box removes empty background "
                                "or margin around the product while keeping the whole product "
                                "visible. Also say which edge the product is visually anchored to "
                                "within that box: 'bottom' if it stands or sits on a surface, "
                                "'top' if it hangs or is shot from below, or 'center' otherwise."
                            ),
                        },
                        {"type": "input_image", "image_url": _openai_image_data_uri(image_path)},
                    ],
                }
            ],
            text_format=ProductZoneDetection,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("Product zone detection did not return a structured response.")
        self._record_text_usage(response, model)
        return parsed


    async def verify_source_product_identity(
        self, *, source_image_path: Path, product_name: str, category_name: str, model: str
    ) -> SourceProductIdentityCheck:
        """Build 6 repair, Critical Defect 1 — shows the model ONLY the real
        source photo (no generated image involved yet) and asks it to judge
        whether that photo actually depicts the named catalog product, before
        any billed image generation is attempted. See
        `SourceProductIdentityCheck` for the verdict contract.
        """
        client = self._require_client()
        category_note = f" (category: {category_name})" if category_name else ""
        response = await client.responses.parse(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"This photo is claimed to be the real product '{product_name}'{category_note}. "
                                "Look carefully at the actual product type, package shape, and any visible label "
                                "text in the photo, and judge whether it plausibly matches the CLAIMED product "
                                "identity — not exact ingredients or claims, just: is this genuinely the same "
                                "kind of product (e.g. a serum vs. a cleanser/wash vs. a cream are DIFFERENT "
                                "product types even within the same brand/line), and does any visible label text "
                                "contradict the claimed name? Return 'MATCH' only when you can clearly confirm "
                                "the photo shows this product. Return 'MISMATCH' when the photo clearly shows a "
                                "different product type or contradicting label text. Return 'UNVERIFIABLE' when "
                                "the photo is too unclear, cropped, or generic to confirm either way — never "
                                "guess a MATCH out of politeness. Report what you actually observed "
                                "(observed_product_type, observed_label_text) as evidence for your verdict, not "
                                "as new confirmed facts about the product."
                            ),
                        },
                        {"type": "input_image", "image_url": _openai_image_data_uri(source_image_path)},
                    ],
                }
            ],
            text_format=SourceProductIdentityCheck,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("Source product identity check did not return a structured response.")
        self._record_text_usage(response, model)
        return parsed


    async def check_product_fidelity(
        self, *, source_image_path: Path, generated_image_path: Path, model: str
    ) -> ProductFidelityCheck:
        """Shows the model both the real source product photo and an AI-recreated
        image side by side and asks it to judge, per concrete aspect, whether the
        recreation kept the actual product — never a single vague yes/no. See
        `ProductFidelityCheck` for the full field list and why a failed/unparseable
        call is never treated as a pass by the caller.
        """
        client = self._require_client()

        def _data_uri(path: Path) -> str:
            return _openai_image_data_uri(
                path
            )

        response = await client.responses.parse(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "The FIRST image is the real, verified source product photo. The "
                                "SECOND image is an AI-recreated marketing image that was supposed "
                                "to keep the exact same product while restyling everything around "
                                "it. Compare them carefully and judge each aspect as 'match', "
                                "'mismatch', or 'uncertain' (use 'uncertain' only when the "
                                "recreated image's framing, angle, or lighting genuinely hides that "
                                "detail — never as a default): package shape, proportions, brand/"
                                "logo, label structure, visible text, cap/pump/dropper or other "
                                "closure, color, and any distinctive marks. Then give an "
                                "overall_verdict: 'PASS' only if the product in the second image is "
                                "clearly and recognizably the same real product with no material "
                                "mismatch; otherwise 'FAIL'. Be strict — a generic lookalike, a "
                                "redesigned package, invented label text, or a different product "
                                "presented as the same one must FAIL even if the overall image looks "
                                "polished and premium."
                            ),
                        },
                        {"type": "input_image", "image_url": _data_uri(source_image_path)},
                        {"type": "input_image", "image_url": _data_uri(generated_image_path)},
                    ],
                }
            ],
            text_format=ProductFidelityCheck,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("Product fidelity check did not return a structured response.")
        self._record_text_usage(response, model)
        return parsed


    async def critique_creative(
        self, *, image_paths: list[Path], source_image_path: Path | None, context: str, model: str,
        reference_target=None, reference_paths: list[Path] | None = None, background_paths: list[Path] | None = None
    ) -> CreativeCritiqueResult:
        """Build 3, Part B — see `AIProvider.critique_creative`'s docstring for
        the contract. Mirrors `check_product_fidelity`/`analyze_visual_style`'s
        own pattern: real image bytes only, never a description.
        """
        if reference_target is not None:
            if not reference_paths or len(reference_paths) != 1 or not background_paths:
                raise ValueError("Target QA requires actual target and native background pixels")
            import hashlib
            if hashlib.sha256(reference_paths[0].read_bytes()).hexdigest() != reference_target.sha256:
                raise ValueError("QA target pixels changed")
        client = self._require_client()

        def _data_uri(path: Path) -> str:
            return _openai_image_data_uri(
                path
            )

        content: list[dict] = [
            {
                "type": "input_text",
                "text": (
                    "You are a senior creative director and platform-marketing critic scoring ONE finished "
                    "marketing creative (or a carousel's ordered set of slides) against the campaign context "
                    "below. Score every dimension 0-100 (0=fails outright, 100=exceptional, professional-grade) "
                    "based only on what you actually see and are told — never invent a fact, claim, or product "
                    "detail not present in the context or the images. Flag anything that should hard-fail "
                    "review in `hard_fails` (be specific and concrete): the product looks pasted onto its "
                    "background, bad shadow/light integration, the product is too small or barely visible, the "
                    "real product has been materially altered from the source photo, the scene conflicts with "
                    "the product, or the composition is technically valid but aesthetically weak/amateurish. "
                    "Set `revision_targets` to `\"copy\"` when the main problem is the text (too long, weak "
                    "CTA, unnatural language) or `\"creative_direction\"` when the main problem is the visual "
                    "scene/composition itself.\n\n"
                    f"Context:\n{context}\n\n"
                    "The FIRST image below (if present) is the real, verified source product photo. The "
                    "remaining image(s) are the finished creative — a single slide, or an ordered carousel "
                    "(judge `carousel_consistency` only when more than one finished-creative image is given)."
                ),
            }
        ]
        if reference_target is not None:
            content.append({"type": "input_text", "text":
                "STRICT TARGET CONTRACT: " + reference_target.model_dump_json() +
                " Compare composition, hierarchy, headline treatment/placement, density, callouts, "
                "negative space, background, lighting, depth, materials, color and premium character. "
                "Return reference_id/sha256 and reference_fidelity 0-100. Reference content is style "
                "authority ONLY, never permission to copy claims, awards or product pixels. "
                "The following image is the OWNER TARGET, not an output or factual source."})
            content.append({"type": "input_image", "image_url": _data_uri(reference_paths[0])})
            content.append({"type": "input_text", "text":
                "Next images are NATIVE BACKGROUNDS. They must contain NO product objects, packaging, "
                "brand marks, labels, generated text, awards or badges. Set background_has_product "
                "true for any such violation; false only after inspecting all. The reference's product "
                "is NOT permitted in backgrounds. Finished outputs must have exactly one authentic "
                "product; set unintended_duplicate_product true for duplicate/ghost/synthetic packages. "
                "Both violations are hard failures. Missing checks fail closed."})
            for path in background_paths:
                content.append({"type": "input_image", "image_url": _data_uri(path)})
            content.append({"type": "input_text", "text": "Next: real SOURCE photo, then FINAL output(s)."})
        if source_image_path is not None:
            content.append({"type": "input_image", "image_url": _data_uri(source_image_path)})
        for image_path in image_paths:
            content.append({"type": "input_image", "image_url": _data_uri(image_path)})

        response = await client.responses.parse(
            model=model,
            input=[{"role": "user", "content": content}],
            text_format=CreativeCritiqueResult,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("Creative critique did not return a structured response.")
        self._record_text_usage(response, model)
        return parsed


    # ---- ResearchProvider -------------------------------------------------------
    async def research(self, query: ResearchQuery, *, model: str) -> ResearchResult:
        client = self._require_client()
        system = (
            "You are a marketing research analyst. Ground every insight in something "
            "verifiable and cite the source URL you relied on. If you cannot find a "
            "reliable, current source for a claim, omit the claim rather than "
            "inventing a statistic — the application will not publish uncited numeric "
            "claims."
        )
        user = (
            f"Research current marketing opportunities for brand '{query.brand_name}', "
            f"category '{query.category}'"
            + (f", product '{query.product}'" if query.product else "")
            + f", targeting '{query.audience}' in {query.geography}, for objective "
            f"'{query.objective}'. Respond in {query.language} where the text is copy "
            "the customer would read (insights/statements themselves), but keep "
            "structural fields in English."
        )
        response = await client.responses.parse(
            model=model,
            tools=[{"type": "web_search"}],
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=ResearchResult,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("Research call did not return a structured ResearchResult.")
        self._record_text_usage(
            response,
            model,
            budget_guard_adjustment_usd=(
                _HARD_BUDGET_WEB_SEARCH_RESERVE_USD
                if self._hard_budget_ledger.enabled
                else 0.0
            ),
        )
        return parsed

    # ---- ResearchProvider (opportunity discovery) --------------------------------
    async def discover_opportunities(self, query: ResearchQuery, *, model: str) -> OpportunityDiscoveryResult:
        client = self._require_client()
        system = (
            "You are a social-media community researcher. Find REAL, currently active "
            "Facebook Groups, subreddits, forums, or Discord servers where the target "
            "audience actually participates. Verify each one exists via web search before "
            "recommending it, and include the source URL(s) where you confirmed it — a "
            "community you cannot verify with a source URL must be omitted, never guessed "
            "or invented. Never fabricate a group name, member count, or URL."
        )
        user = (
            f"Find posting communities for brand '{query.brand_name}', category "
            f"'{query.category}'"
            + (f", product '{query.product}'" if query.product else "")
            + f", targeting '{query.audience}' in {query.geography}, for objective "
            f"'{query.objective}'. For each community, note whether promotional posts are "
            "typically allowed (many groups ban direct selling — flag this) and suggest a "
            "content style that fits that community's norms rather than a generic ad."
        )
        response = await client.responses.parse(
            model=model,
            tools=[{"type": "web_search"}],
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=OpportunityDiscoveryResult,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("Opportunity discovery call did not return a structured result.")
        self._record_text_usage(
            response,
            model,
            budget_guard_adjustment_usd=(
                _HARD_BUDGET_WEB_SEARCH_RESERVE_USD
                if self._hard_budget_ledger.enabled
                else 0.0
            ),
        )
        return parsed

    # ---- ImageProvider ----------------------------------------------------------
    async def generate(
        self, *, prompt: str, size: str, model: str, reference_images: list[Path] | None = None,
        quality: str = "high",
    ) -> bytes:
        client = self._require_client()

        self._validate_gpt_image_2_5_call(
            model=model,
            quality=quality,
            size=size,
            count=1,
        )

        if reference_images:
            if self._bounded_acceptance:
                if len(reference_images) != 1:
                    raise HardBudgetExceededError("BOUNDED_REFERENCE_COUNT_EXCEEDED")
                for path in reference_images:
                    if Path(path).stat().st_size > _SUNBURST_PAYLOAD_LIMITS["reference_file_bytes"]:
                        raise HardBudgetExceededError("BOUNDED_REFERENCE_FILE_BYTES_EXCEEDED")
                    with Image.open(path) as source:
                        w, h = source.size
                        if w > 2048 or h > 2048 or w*h > 2048*2048:
                            raise HardBudgetExceededError("BOUNDED_REFERENCE_PIXELS_EXCEEDED")
            opened = [
                _openai_image_upload(
                    path
                )
                for path in reference_images
            ]

            try:
                response = await client.images.edit(
                    model=model,
                    image=opened,
                    prompt=prompt,
                    size=size,
                    quality=quality,
                )

            finally:
                for handle in opened:
                    handle.close()

        else:
            response = await client.images.generate(
                model=model,
                prompt=prompt,
                size=size,
                n=1,
                quality=quality,
            )

        b64_data = (
            response.data[0].b64_json
        )

        if not b64_data:
            raise ValueError(
                "Image generation did not return image data."
            )

        self._record_image_usage(
            model,
            quality,
            count=1,
            response=response,
        )

        return base64.b64decode(
            b64_data
        )


    async def edit(
        self,
        *,
        base_image: Path,
        prompt: str,
        model: str,
        mask: Path | None = None,
        quality: str = "high",
    ) -> bytes:
        client = self._require_client()

        self._validate_gpt_image_2_5_call(
            model=model,
            quality=quality,
            size=None,
            count=1,
        )

        image_file = (
            _openai_image_upload(
                base_image
            )
        )

        try:
            kwargs = {
                "model": model,
                "image": image_file,
                "prompt": prompt,
                "quality": quality,
            }

            if mask is not None:
                mask_file = (
                    _openai_image_upload(
                        mask
                    )
                )

                try:
                    kwargs["mask"] = (
                        mask_file
                    )

                    response = (
                        await client.images.edit(
                            **kwargs
                        )
                    )

                finally:
                    mask_file.close()

            else:
                response = (
                    await client.images.edit(
                        **kwargs
                    )
                )

        finally:
            image_file.close()

        b64_data = (
            response.data[0].b64_json
        )

        if not b64_data:
            raise ValueError(
                "Image edit did not return image data."
            )

        self._record_image_usage(
            model,
            quality,
            count=1,
        )

        return base64.b64decode(
            b64_data
        )


def _runtime_bool(
    value,
) -> bool:
    if isinstance(
        value,
        bool,
    ):
        return value

    if value is None:
        return False

    normalized = str(
        value
    ).strip().lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "",
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    raise ValueError(
        "Invalid boolean runtime setting: "
        + repr(value)
    )


def _runtime_positive_int(
    value,
    *,
    setting_name: str,
) -> int | None:
    if value in (
        None,
        "",
    ):
        return None

    try:
        parsed = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            setting_name
            + " must be a positive integer."
        ) from exc

    if parsed <= 0:
        raise ValueError(
            setting_name
            + " must be a positive integer."
        )

    return parsed


def openai_provider_from_effective_settings(
    effective: dict,
    *,
    hard_budget_usd: float | None = None,
    max_image_calls_override: int | None = None,
    acceptance_call_limits: dict[str, int] | None = None,
    bounded_acceptance: bool = False,
) -> OpenAIProvider:
    """Create the canonical runtime OpenAI provider from effective settings.

    GPT Image 2.5 remains fail-closed unless a project id, an explicit
    provider-hard-limit attestation, and a positive local image-call limit
    are all configured. Text-only OpenAI operations remain usable while
    those image-specific controls are intentionally unconfigured.
    """
    return OpenAIProvider(
        api_key=(
            str(
                effective.get(
                    "openai_api_key"
                )
                or ""
            ).strip()
            or None
        ),
        hard_budget_usd=hard_budget_usd,
        acceptance_call_limits=acceptance_call_limits,
        bounded_acceptance=bounded_acceptance,
        project_id=str(
            effective.get(
                "openai_project_id"
            )
            or ""
        ).strip(),
        provider_hard_limit_attested=(
            _runtime_bool(
                effective.get(
                    "openai_project_hard_limit_attested",
                    False,
                )
            )
        ),
        max_image_calls=(
            max_image_calls_override
            if max_image_calls_override is not None
            else _runtime_positive_int(
                effective.get(
                    "openai_max_image_calls"
                ),
                setting_name="openai_max_image_calls",
            )
        ),
    )

