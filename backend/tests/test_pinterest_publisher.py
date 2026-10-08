"""Zero-cost deterministic tests for MKT-PUB-0002 Pinterest provider."""
import json
import httpx
import pytest
from app.services.ai.base import PublishCopy, PublishTarget
from app.services.publishing.pinterest_provider import PinterestPublishingProvider

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))

@pytest.mark.asyncio
async def test_publish_without_token_fails_without_network(tmp_path):
    image = tmp_path / "slide.png"; image.write_bytes(b"png")
    result = await PinterestPublishingProvider("").publish(target=PublishTarget(provider="pinterest", external_id="board", public_asset_url="https://example.test/slide.png"), assets=[image], copy=PublishCopy(caption="Hello"))
    assert result.success is False and "access token" in result.error.lower()

@pytest.mark.asyncio
async def test_publish_requires_board_asset_and_public_url(tmp_path):
    image = tmp_path / "slide.png"; image.write_bytes(b"png")
    p = PinterestPublishingProvider("token")
    assert "board id" in (await p.publish(target=PublishTarget(provider="pinterest", external_id="", public_asset_url="https://e/1.png"), assets=[image], copy=PublishCopy(caption="x"))).error.lower()
    assert "rendered image" in (await p.publish(target=PublishTarget(provider="pinterest", external_id="b", public_asset_url="https://e/1.png"), assets=[], copy=PublishCopy(caption="x"))).error.lower()
    assert "public" in (await p.publish(target=PublishTarget(provider="pinterest", external_id="b"), assets=[image], copy=PublishCopy(caption="x"))).error.lower()

@pytest.mark.asyncio
async def test_publish_creates_image_url_pin(tmp_path):
    image = tmp_path / "slide.png"; image.write_bytes(b"png")
    def handler(request):
        assert request.method == "POST" and request.url.path == "/v5/pins"
        assert request.headers["authorization"] == "Bearer token"
        body = json.loads(request.content)
        assert body["board_id"] == "board-123"
        assert body["description"] == "Premium Japan find\n\n#japan #beauty"
        assert body["media_source"] == {"source_type": "image_url", "url": "https://public.example/slide.png"}
        return httpx.Response(201, json={"id": "pin-999"})
    p = PinterestPublishingProvider("token", client=_client(handler))
    result = await p.publish(target=PublishTarget(provider="pinterest", external_id="board-123", public_asset_url="https://public.example/slide.png"), assets=[image], copy=PublishCopy(caption="Premium Japan find", hashtags=["japan", "#beauty"]))
    assert result.success is True and result.external_post_id == "pin-999"
    assert result.url == "https://www.pinterest.com/pin/pin-999/"

@pytest.mark.asyncio
async def test_publish_error_is_fail_closed(tmp_path):
    image = tmp_path / "slide.png"; image.write_bytes(b"png")
    p = PinterestPublishingProvider("token", client=_client(lambda request: httpx.Response(403, json={"message": "PINNER_DATA_ACCESS_DENIED"})))
    result = await p.publish(target=PublishTarget(provider="pinterest", external_id="b", public_asset_url="https://e/1.png"), assets=[image], copy=PublishCopy(caption="x"))
    assert result.success is False and result.error == "PINNER_DATA_ACCESS_DENIED"

@pytest.mark.asyncio
async def test_fetch_metrics_fails_closed_without_network():
    network_called = False

    def handler(request):
        nonlocal network_called
        network_called = True
        raise AssertionError(
            "Pinterest metrics must not make a network request."
        )

    provider = PinterestPublishingProvider(
        "token",
        client=_client(handler),
    )

    result = await provider.fetch_metrics(
        provider="pinterest",
        external_post_id="pin-999",
    )

    assert result.success is False
    assert result.metrics == {}
    assert result.error == (
        "Pinterest metrics sync is not supported in MKT-PUB-0002."
    )
    assert network_called is False
