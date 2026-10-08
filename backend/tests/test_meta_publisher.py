"""Direct unit tests of `MetaPublishingProvider` — the one module allowed to talk to
Meta's Graph API. No real network call or access token is used: `httpx.MockTransport`
intercepts every request and returns a canned response, so these tests verify the
provider builds the right request (URL, fields, file attachment) for each of
Facebook's and Instagram's very different publishing flows, and turns a Graph API
error response into a clear `PublishResult(success=False, ...)` rather than raising.
"""
from __future__ import annotations

import httpx
import pytest

from app.services.ai.base import PublishCopy, PublishTarget
from app.services.publishing.meta_provider import MetaPublishingProvider


def _client_with_handler(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_publish_without_access_token_fails_without_a_network_call():
    provider = MetaPublishingProvider("")
    result = await provider.publish(
        target=PublishTarget(provider="facebook_page", external_id="123"),
        assets=[],
        copy=PublishCopy(caption="Hello"),
    )
    assert result.success is False
    assert "access token" in result.error


@pytest.mark.asyncio
async def test_facebook_photo_upload_posts_the_real_file_and_caption(tmp_path):
    image = tmp_path / "slide.png"
    image.write_bytes(b"fake-png-bytes")
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        assert request.url.path == "/v21.0/999888777/photos"
        return httpx.Response(200, json={"id": "photo_1", "post_id": "999888777_555"})

    provider = MetaPublishingProvider("page-token", client=_client_with_handler(handler))
    result = await provider.publish(
        target=PublishTarget(provider="facebook_page", external_id="999888777"),
        assets=[image],
        copy=PublishCopy(caption="New drop!", hashtags=["skincare", "japan"]),
    )

    assert result.success is True
    assert result.external_post_id == "999888777_555"
    assert result.url == "https://www.facebook.com/999888777_555"
    assert len(requests_seen) == 1
    body = requests_seen[0].content.decode("utf-8", errors="ignore")
    assert "#skincare" in body and "#japan" in body
    assert "fake-png-bytes" in body  # the real file bytes were attached, not a URL reference


@pytest.mark.asyncio
async def test_facebook_photo_upload_with_no_rendered_asset_fails_cleanly():
    provider = MetaPublishingProvider("page-token", client=_client_with_handler(lambda r: httpx.Response(200, json={})))
    result = await provider.publish(
        target=PublishTarget(provider="facebook_page", external_id="999888777"),
        assets=[],
        copy=PublishCopy(caption="New drop!"),
    )
    assert result.success is False
    assert "rendered image" in result.error


@pytest.mark.asyncio
async def test_instagram_without_public_asset_url_fails_with_actionable_message(tmp_path):
    """This is the real Meta constraint: Instagram's Content Publishing API only
    accepts an `image_url` it fetches itself — there is no file-upload option for a
    still image. Without a public URL configured, this must fail clearly rather than
    send a request Meta will reject in a more confusing way.
    """
    provider = MetaPublishingProvider(
        "page-token", client=_client_with_handler(lambda r: httpx.Response(200, json={}))
    )
    result = await provider.publish(
        target=PublishTarget(provider="instagram", external_id="ig-123"),  # no public_asset_url
        assets=[],
        copy=PublishCopy(caption="New drop!"),
    )
    assert result.success is False
    assert "public url" in result.error.lower()


@pytest.mark.asyncio
async def test_instagram_publish_does_the_two_step_container_then_publish_flow():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v21.0/ig-123/media":
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path == "/v21.0/ig-123/media_publish":
            return httpx.Response(200, json={"id": "ig-post-1"})
        return httpx.Response(404, json={"error": {"message": "unexpected path"}})

    provider = MetaPublishingProvider("page-token", client=_client_with_handler(handler))
    result = await provider.publish(
        target=PublishTarget(
            provider="instagram", external_id="ig-123",
            public_asset_url="https://example.ngrok.app/api/campaigns/c1/slides/1/image",
        ),
        assets=[],
        copy=PublishCopy(caption="New drop!"),
    )

    assert result.success is True
    assert result.external_post_id == "ig-post-1"
    assert len(calls) == 2
    first_body = calls[0].content.decode("utf-8", errors="ignore")
    assert "ngrok.app" in first_body
    second_body = calls[1].content.decode("utf-8", errors="ignore")
    assert "container-1" in second_body


@pytest.mark.asyncio
async def test_graph_api_error_response_becomes_a_clear_publish_failure(tmp_path):
    image = tmp_path / "slide.png"
    image.write_bytes(b"fake-png-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token."}})

    provider = MetaPublishingProvider("bad-token", client=_client_with_handler(handler))
    result = await provider.publish(
        target=PublishTarget(provider="facebook_page", external_id="999888777"),
        assets=[image],
        copy=PublishCopy(caption="New drop!"),
    )
    assert result.success is False
    assert result.error == "Invalid OAuth access token."


@pytest.mark.asyncio
async def test_unknown_provider_fails_cleanly():
    provider = MetaPublishingProvider("page-token")
    result = await provider.publish(
        target=PublishTarget(provider="linkedin", external_id="x"), assets=[], copy=PublishCopy(caption="hi"),
    )
    assert result.success is False
    assert "Unknown publish provider" in result.error


@pytest.mark.asyncio
async def test_fetch_metrics_without_token_or_post_id_fails_without_a_network_call():
    provider = MetaPublishingProvider("")
    result = await provider.fetch_metrics(provider="facebook_page", external_post_id="123_456")
    assert result.success is False
    assert "access token" in result.error

    provider = MetaPublishingProvider("page-token")
    result = await provider.fetch_metrics(provider="facebook_page", external_post_id="")
    assert result.success is False
    assert "external_post_id" in result.error


@pytest.mark.asyncio
async def test_fetch_facebook_metrics_combines_stable_counts_and_best_effort_insights():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v21.0/123_456":
            return httpx.Response(
                200,
                json={
                    "likes": {"summary": {"total_count": 42}},
                    "comments": {"summary": {"total_count": 7}},
                    "shares": {"count": 3},
                },
            )
        if request.url.path == "/v21.0/123_456/insights":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"name": "post_impressions", "values": [{"value": 900}]},
                        {"name": "post_impressions_unique", "values": [{"value": 500}]},
                    ]
                },
            )
        return httpx.Response(404, json={"error": {"message": "unexpected path"}})

    provider = MetaPublishingProvider("page-token", client=_client_with_handler(handler))
    result = await provider.fetch_metrics(provider="facebook_page", external_post_id="123_456")

    assert result.success is True
    assert result.metrics == {"likes": 42, "comments": 7, "shares": 3, "impressions": 900, "reach": 500}


@pytest.mark.asyncio
async def test_fetch_facebook_metrics_still_succeeds_when_insights_edge_fails():
    """This is the real-world case that matters: Meta has repeatedly deprecated or
    restricted Page post insight metrics, so a sync must not fail entirely just
    because the volatile Insights edge rejected a metric name — the stable
    like/comment/share counts are still worth recording.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v21.0/123_456":
            return httpx.Response(200, json={"likes": {"summary": {"total_count": 10}}})
        if request.url.path == "/v21.0/123_456/insights":
            return httpx.Response(400, json={"error": {"message": "(#100) metric is deprecated"}})
        return httpx.Response(404, json={"error": {"message": "unexpected path"}})

    provider = MetaPublishingProvider("page-token", client=_client_with_handler(handler))
    result = await provider.fetch_metrics(provider="facebook_page", external_post_id="123_456")

    assert result.success is True
    assert result.metrics == {"likes": 10}


@pytest.mark.asyncio
async def test_fetch_instagram_metrics_combines_stable_counts_and_best_effort_insights():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v21.0/ig-media-1":
            return httpx.Response(200, json={"like_count": 88, "comments_count": 4})
        if request.url.path == "/v21.0/ig-media-1/insights":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"name": "reach", "values": [{"value": 700}]},
                        {"name": "saved", "total_value": {"value": 12}},
                    ]
                },
            )
        return httpx.Response(404, json={"error": {"message": "unexpected path"}})

    provider = MetaPublishingProvider("page-token", client=_client_with_handler(handler))
    result = await provider.fetch_metrics(provider="instagram", external_post_id="ig-media-1")

    assert result.success is True
    assert result.metrics == {"likes": 88, "comments": 4, "reach": 700, "saves": 12}


@pytest.mark.asyncio
async def test_fetch_metrics_graph_api_error_on_stable_fields_fails_the_whole_sync():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token."}})

    provider = MetaPublishingProvider("bad-token", client=_client_with_handler(handler))
    result = await provider.fetch_metrics(provider="facebook_page", external_post_id="123_456")
    assert result.success is False
    assert result.error == "Invalid OAuth access token."
