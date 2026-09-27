"""Meta (Facebook Page + Instagram) implementation of `PublishingProvider` (brief
sections 47/48). This is the ONLY module allowed to talk to Meta's Graph API
directly — business logic and API routes must only ever import the
`PublishingProvider` Protocol (`app/services/ai/base.py`), the same isolation
discipline `OpenAIProvider` keeps for the `openai` SDK.

Two real, verified constraints from Meta's own developer documentation shape this
implementation (see `docs/architecture.md` for the write-up and sources):

- A Facebook Page photo post (`POST /{page-id}/photos`) accepts the image as a
  direct multipart file upload (the `source` field) — no public hosting required.
  This app's rendered creatives live on the user's own disk, so this is the easy
  case: the file goes straight from OUTPUT_ROOT to Meta's servers.
- Instagram's Content Publishing API is a two-step flow (`POST /{ig-user-id}/media`
  to create a container, then `POST /{ig-user-id}/media_publish` to publish it) and
  only accepts an `image_url` that Meta's own servers fetch over the public
  internet — there is no direct file-upload option for a still image. A locally
  rendered creative therefore cannot be posted to Instagram unless it is reachable
  at a public URL first (`PublishTarget.public_asset_url` — see the README's
  "Instagram auto-publish" section for how to set one up, typically a tunnel like
  ngrok pointed at this backend). Attempting Instagram without one returns a clear,
  actionable `PublishResult` failure rather than a confusing Graph API error, and
  nothing is posted.

Uses `httpx` directly rather than a vendor SDK — there is no official Meta Python
SDK dependency in this project, and the Graph API is a plain REST API, so a small
direct client keeps this module's one job (talk to Meta) legible and easy to test
against a fake transport (see `tests/test_meta_publisher.py`) with no real network
call or token needed.

This module also implements `fetch_metrics` — the read-back counterpart to
`publish`, for automatically pulling real like/comment/reach/save counts for a
post instead of a human typing them into the Publishing panel by hand (sections
36-38). See that method's docstring for why its stable-fields vs. Insights-edge
split exists: Meta's Insights metric names have historically been far more
volatile than the publishing endpoints above.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from ..ai.base import MetricsFetchResult, PublishCopy, PublishResult, PublishTarget

DEFAULT_GRAPH_API_VERSION = "v21.0"


class MetaAPIError(RuntimeError):
    """A Graph API call returned an error payload. Caught inside `publish()` and
    turned into a `PublishResult(success=False, error=...)` rather than propagating —
    a failed post is expected, recoverable application state, not a bug.
    """


def _format_caption(copy: PublishCopy) -> str:
    caption = copy.caption.strip()
    hashtags = " ".join(f"#{h.lstrip('#')}" for h in copy.hashtags if h.strip())
    return f"{caption}\n\n{hashtags}".strip() if hashtags else caption


class MetaPublishingProvider:
    """Implements `PublishingProvider` against Meta's Graph API. Construct with a
    long-lived Page access token (see README's "Facebook Page / Instagram
    auto-publish" section for how to get one) — the same token authorizes both a
    Facebook Page post and, when that Page has a linked Instagram Business account,
    an Instagram post via that account's own Graph API edges.

    `client`, when given, is used for every request instead of a fresh
    `httpx.AsyncClient()` per call — tests inject an `httpx.AsyncClient` built on
    `httpx.MockTransport` here so no real network call is ever made.
    """

    def __init__(
        self, access_token: str, *, api_version: str = DEFAULT_GRAPH_API_VERSION,
        client: httpx.AsyncClient | None = None,
    ):
        self._access_token = access_token
        self._base_url = f"https://graph.facebook.com/{api_version}"
        self._client = client

    async def _post(self, path: str, *, data: dict | None = None, files: dict | None = None) -> dict:
        if self._client is not None:
            response = await self._client.post(f"{self._base_url}{path}", data=data, files=files, timeout=60.0)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self._base_url}{path}", data=data, files=files, timeout=60.0)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            message = (payload.get("error") or {}).get("message") or response.text or "Unknown Graph API error."
            raise MetaAPIError(message)
        return payload

    async def _get(self, path: str, *, params: dict) -> dict:
        if self._client is not None:
            response = await self._client.get(f"{self._base_url}{path}", params=params, timeout=30.0)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}{path}", params=params, timeout=30.0)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            message = (payload.get("error") or {}).get("message") or response.text or "Unknown Graph API error."
            raise MetaAPIError(message)
        return payload

    async def publish(self, *, target: PublishTarget, assets: list[Path], copy: PublishCopy) -> PublishResult:
        if not self._access_token:
            return PublishResult(
                success=False,
                error="No Facebook/Instagram access token configured. Set it in Settings first.",
            )
        try:
            if target.provider == "facebook_page":
                if not assets:
                    return PublishResult(
                        success=False, error="No rendered image to publish — render a creative for this slide first."
                    )
                return await self._publish_facebook_photo(target, assets[0], copy)
            if target.provider == "instagram":
                return await self._publish_instagram_photo(target, copy)
            return PublishResult(success=False, error=f"Unknown publish provider '{target.provider}'.")
        except MetaAPIError as exc:
            return PublishResult(success=False, error=str(exc))

    async def _publish_facebook_photo(
        self, target: PublishTarget, image_path: Path, copy: PublishCopy
    ) -> PublishResult:
        with image_path.open("rb") as f:
            payload = await self._post(
                f"/{target.external_id}/photos",
                data={"caption": _format_caption(copy), "access_token": self._access_token},
                files={"source": (image_path.name, f, "image/png")},
            )
        post_id = payload.get("post_id") or payload.get("id", "")
        return PublishResult(
            success=True, external_post_id=post_id, url=f"https://www.facebook.com/{post_id}" if post_id else "",
        )

    async def _publish_instagram_photo(self, target: PublishTarget, copy: PublishCopy) -> PublishResult:
        if not target.public_asset_url:
            return PublishResult(
                success=False,
                error=(
                    "Instagram's API requires the image to be fetchable at a public URL — it "
                    "cannot accept a direct file upload. Set PUBLIC_BASE_URL in Settings (a "
                    "URL Meta's servers can reach, e.g. an ngrok tunnel pointed at this "
                    "backend) so the generated creative has a public address. See the "
                    "README's 'Instagram auto-publish' section."
                ),
            )
        container = await self._post(
            f"/{target.external_id}/media",
            data={
                "image_url": target.public_asset_url,
                "caption": _format_caption(copy),
                "access_token": self._access_token,
            },
        )
        creation_id = container.get("id")
        if not creation_id:
            return PublishResult(success=False, error="Instagram did not return a media container id.")
        published = await self._post(
            f"/{target.external_id}/media_publish",
            data={"creation_id": creation_id, "access_token": self._access_token},
        )
        post_id = published.get("id", "")
        return PublishResult(success=True, external_post_id=post_id, url="")

    async def fetch_metrics(self, *, provider: str, external_post_id: str) -> MetricsFetchResult:
        """Reads back real engagement numbers for a post. Two tiers, deliberately
        kept separate:

        - **Stable fields** (like/comment counts via the post/media's own `fields`
          expansion) — this is the long-established, rarely-changed part of the
          Graph API, so a failure here fails the whole sync.
        - **The Insights edge** (impressions/reach/saved/shares) — genuinely more
          volatile; Meta has repeatedly deprecated and renamed metrics here across
          API versions. Fetched best-effort: if the whole insights call fails (an
          unsupported metric name, a permission gap), the stable counts above are
          still returned rather than failing the entire sync.

        Only metrics the platform actually returned end up in the result — never
        filled in as 0 for something that wasn't fetched, matching this app's
        "no fake output" rule for research/opportunities/performance data
        everywhere else.
        """
        if not self._access_token:
            return MetricsFetchResult(success=False, error="No Facebook/Instagram access token configured.")
        if not external_post_id:
            return MetricsFetchResult(success=False, error="This publication has no external_post_id to sync from.")
        try:
            if provider == "facebook_page":
                return await self._fetch_facebook_metrics(external_post_id)
            if provider == "instagram":
                return await self._fetch_instagram_metrics(external_post_id)
            return MetricsFetchResult(success=False, error=f"Unknown publish provider '{provider}'.")
        except MetaAPIError as exc:
            return MetricsFetchResult(success=False, error=str(exc))

    @staticmethod
    def _insight_value(row: dict) -> int | None:
        values = row.get("values") or []
        if values and values[0].get("value") is not None:
            return values[0]["value"]
        total_value = row.get("total_value") or {}
        return total_value.get("value")

    async def _fetch_facebook_metrics(self, post_id: str) -> MetricsFetchResult:
        counts = await self._get(
            f"/{post_id}",
            params={
                "fields": "likes.summary(true).limit(0),comments.summary(true).limit(0),shares",
                "access_token": self._access_token,
            },
        )
        metrics: dict[str, int] = {}
        likes_total = (counts.get("likes") or {}).get("summary", {}).get("total_count")
        if likes_total is not None:
            metrics["likes"] = likes_total
        comments_total = (counts.get("comments") or {}).get("summary", {}).get("total_count")
        if comments_total is not None:
            metrics["comments"] = comments_total
        shares_count = (counts.get("shares") or {}).get("count")
        if shares_count is not None:
            metrics["shares"] = shares_count

        try:
            insights = await self._get(
                f"/{post_id}/insights",
                params={"metric": "post_impressions,post_impressions_unique", "access_token": self._access_token},
            )
            for row in insights.get("data", []):
                value = self._insight_value(row)
                if value is None:
                    continue
                if row.get("name") == "post_impressions":
                    metrics["impressions"] = value
                elif row.get("name") == "post_impressions_unique":
                    metrics["reach"] = value
        except MetaAPIError:
            pass  # best-effort — the stable counts above still make this a real sync

        return MetricsFetchResult(success=True, metrics=metrics)

    async def _fetch_instagram_metrics(self, media_id: str) -> MetricsFetchResult:
        counts = await self._get(
            f"/{media_id}", params={"fields": "like_count,comments_count", "access_token": self._access_token},
        )
        metrics: dict[str, int] = {}
        if counts.get("like_count") is not None:
            metrics["likes"] = counts["like_count"]
        if counts.get("comments_count") is not None:
            metrics["comments"] = counts["comments_count"]

        try:
            insights = await self._get(
                f"/{media_id}/insights",
                params={"metric": "reach,saved,shares", "access_token": self._access_token},
            )
            for row in insights.get("data", []):
                value = self._insight_value(row)
                if value is None:
                    continue
                name = row.get("name")
                if name == "reach":
                    metrics["reach"] = value
                elif name == "saved":
                    metrics["saves"] = value
                elif name == "shares":
                    metrics["shares"] = value
        except MetaAPIError:
            pass  # best-effort — the stable counts above still make this a real sync

        return MetricsFetchResult(success=True, metrics=metrics)
