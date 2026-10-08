"""Pinterest organic image Pin implementation of PublishingProvider."""
from __future__ import annotations
from pathlib import Path
import httpx
from ..ai.base import MetricsFetchResult, PublishCopy, PublishResult, PublishTarget

DEFAULT_PINTEREST_API_BASE_URL = "https://api.pinterest.com/v5"

class PinterestAPIError(RuntimeError):
    pass

def _description(copy: PublishCopy) -> str:
    caption = copy.caption.strip()
    hashtags = " ".join(f"#{h.lstrip('#')}" for h in copy.hashtags if h.strip())
    return f"{caption}\n\n{hashtags}".strip() if hashtags else caption

class PinterestPublishingProvider:
    def __init__(self, access_token: str, *, client: httpx.AsyncClient | None = None, base_url: str = DEFAULT_PINTEREST_API_BASE_URL):
        self._access_token = access_token
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def _request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}
        if self._client is not None:
            response = await self._client.request(method, f"{self._base_url}{path}", headers=headers, json=json, params=params, timeout=60.0)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, f"{self._base_url}{path}", headers=headers, json=json, params=params, timeout=60.0)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            message = payload.get("message") or (payload.get("error") or {}).get("message") or response.text or "Unknown Pinterest API error."
            raise PinterestAPIError(message)
        return payload

    async def publish(self, *, target: PublishTarget, assets: list[Path], copy: PublishCopy) -> PublishResult:
        if not self._access_token:
            return PublishResult(success=False, error="No Pinterest access token configured. Set it in Settings first.")
        if target.provider != "pinterest":
            return PublishResult(success=False, error=f"Unknown publish provider '{target.provider}'.")
        if not target.external_id:
            return PublishResult(success=False, error="Pinterest board ID is not configured. Set it in Settings first.")
        if not assets or not assets[0].exists():
            return PublishResult(success=False, error="No rendered image to publish - render a creative for this slide first.")
        if not target.public_asset_url:
            return PublishResult(success=False, error="Pinterest image Pin creation requires a publicly fetchable image URL. Set Public base URL in Settings first.")
        try:
            payload = await self._request("POST", "/pins", json={
                "board_id": target.external_id,
                "description": _description(copy),
                "media_source": {"source_type": "image_url", "url": target.public_asset_url},
            })
        except PinterestAPIError as exc:
            return PublishResult(success=False, error=str(exc))
        pin_id = str(payload.get("id") or "")
        if not pin_id:
            return PublishResult(success=False, error="Pinterest did not return a Pin id.")
        return PublishResult(success=True, external_post_id=pin_id, url=f"https://www.pinterest.com/pin/{pin_id}/")

    async def fetch_metrics(self, *, provider: str, external_post_id: str) -> MetricsFetchResult:
        """Fail closed: Pinterest analytics are out of scope for MKT-PUB-0002.

        This connector supports organic Pin publishing only. Metrics sync is
        intentionally disabled in this build and must not perform any network
        request.
        """
        return MetricsFetchResult(
            success=False,
            error="Pinterest metrics sync is not supported in MKT-PUB-0002.",
        )
