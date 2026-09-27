"""Build 6R byte-sniffed OpenAI image payload tests."""

from io import BytesIO
from pathlib import Path
import base64
import inspect

from PIL import Image

import app.services.ai.openai_provider as provider

from app.services.ai.openai_provider import (
    OpenAIProvider,
    _normalize_openai_image_bytes,
    _openai_image_data_uri,
    _openai_image_upload,
)


def _write_png(
    path: Path,
):
    image = Image.new(
        "RGB",
        (32, 24),
        (40, 120, 180),
    )

    image.save(
        path,
        format="PNG",
    )


def _write_bmp_with_wrong_suffix(
    path: Path,
):
    image = Image.new(
        "RGB",
        (32, 24),
        (220, 60, 80),
    )

    image.save(
        path,
        format="BMP",
    )


def test_supported_png_uses_detected_format_and_original_bytes(
    tmp_path,
):
    path = (
        tmp_path
        / "misleading.jpg"
    )

    _write_png(
        path
    )

    original = (
        path.read_bytes()
    )

    payload, mime, extension = (
        _normalize_openai_image_bytes(
            path
        )
    )

    assert payload == original
    assert mime == "image/png"
    assert extension == "png"


def test_unsupported_decoded_format_is_transcoded_to_png(
    tmp_path,
):
    path = (
        tmp_path
        / "actually-bmp.png"
    )

    _write_bmp_with_wrong_suffix(
        path
    )

    payload, mime, extension = (
        _normalize_openai_image_bytes(
            path
        )
    )

    assert mime == "image/png"
    assert extension == "png"

    assert payload.startswith(
        b"\x89PNG\r\n\x1a\n"
    )

    with Image.open(
        BytesIO(payload)
    ) as image:
        assert image.format == "PNG"
        assert image.size == (32, 24)


def test_data_uri_uses_decoded_format_not_filename_suffix(
    tmp_path,
):
    path = (
        tmp_path
        / "wrong.jpg"
    )

    _write_png(
        path
    )

    uri = (
        _openai_image_data_uri(
            path
        )
    )

    assert uri.startswith(
        "data:image/png;base64,"
    )

    raw = base64.b64decode(
        uri.split(",", 1)[1]
    )

    assert raw.startswith(
        b"\x89PNG\r\n\x1a\n"
    )


def test_upload_gets_matching_supported_filename(
    tmp_path,
):
    path = (
        tmp_path
        / "actually-bmp.png"
    )

    _write_bmp_with_wrong_suffix(
        path
    )

    stream = (
        _openai_image_upload(
            path
        )
    )

    try:
        assert stream.name.endswith(
            ".png"
        )

        payload = stream.read()

        assert payload.startswith(
            b"\x89PNG\r\n\x1a\n"
        )

    finally:
        stream.close()


def test_provider_contains_no_filename_suffix_mime_derivation():
    source = inspect.getsource(
        provider
    )

    assert (
        'suffix.lstrip(".").lower()'
        not in source
    )

    assert (
        "data:image/{ext};base64"
        not in source
    )


def test_identity_method_uses_central_normalizer():
    source = inspect.getsource(
        OpenAIProvider.verify_source_product_identity
    )

    assert (
        "_openai_image_data_uri"
        in source
    )

    assert (
        "source_image_path"
        in source
    )


def test_fidelity_and_critique_use_central_normalizer():
    fidelity = inspect.getsource(
        OpenAIProvider.check_product_fidelity
    )

    critique = inspect.getsource(
        OpenAIProvider.critique_creative
    )

    assert (
        "_openai_image_data_uri"
        in fidelity
    )

    assert (
        "_openai_image_data_uri"
        in critique
    )


def test_reference_generation_uses_normalized_upload():
    source = inspect.getsource(
        OpenAIProvider.generate
    )

    assert (
        "_openai_image_upload"
        in source
    )
