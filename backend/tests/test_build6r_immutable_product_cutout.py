
from pathlib import Path
import hashlib
import inspect
import json

from PIL import Image, ImageDraw

from app.services.creative.background import (
    ImmutableProductCutoutIsolator,
    get_isolator,
)
from app.services.creative import pipeline


def _sha256(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def _white_source(
    path: Path,
) -> None:
    image = Image.new(
        "RGB",
        (80, 100),
        (250, 250, 250),
    )

    draw = ImageDraw.Draw(
        image
    )

    # Colored product body.
    draw.rectangle(
        (20, 12, 60, 90),
        fill=(220, 170, 40),
    )

    # Deliberately white detail INSIDE the
    # product. Border-connected removal must
    # preserve this because it is not connected
    # to the outer background.
    draw.rectangle(
        (31, 38, 49, 55),
        fill=(250, 250, 250),
    )

    image.save(
        path,
        "PNG",
    )


def test_immutable_cutout_removes_only_border_connected_background(
    tmp_path,
):
    source = (
        tmp_path
        / "product.png"
    )

    _white_source(
        source
    )

    source_sha_before = (
        _sha256(
            source
        )
    )

    cache = (
        tmp_path
        / "cache"
    )

    isolator = get_isolator(
        enabled=False,
        source_path=source,
        prefer_immutable=True,
        cache_root=cache,
    )

    with Image.open(
        source
    ) as image:
        result = isolator.isolate(
            image
        )

    assert isinstance(
        isolator,
        ImmutableProductCutoutIsolator,
    )

    assert result.mode == "RGBA"

    # Outer background removed.
    assert result.getpixel(
        (2, 2)
    )[3] == 0

    # Product remains opaque.
    assert result.getpixel(
        (25, 25)
    )[3] >= 250

    # Internal white product detail remains.
    assert result.getpixel(
        (40, 45)
    )[3] >= 250

    assert (
        _sha256(
            source
        )
        == source_sha_before
    )


def test_cutout_cache_is_keyed_by_exact_source_sha(
    tmp_path,
):
    source = (
        tmp_path
        / "product.png"
    )

    _white_source(
        source
    )

    source_sha = (
        _sha256(
            source
        )
    )

    cache = (
        tmp_path
        / "derived-products"
    )

    isolator = get_isolator(
        enabled=False,
        source_path=source,
        prefer_immutable=True,
        cache_root=cache,
    )

    with Image.open(
        source
    ) as image:
        first = isolator.isolate(
            image
        )

    directory = (
        cache
        / source_sha
    )

    product_path = (
        directory
        / "product-rgba.png"
    )

    metadata_path = (
        directory
        / "isolation.json"
    )

    assert product_path.is_file()
    assert metadata_path.is_file()

    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        metadata[
            "source_sha256"
        ]
        == source_sha
    )

    assert (
        metadata[
            "algorithm_version"
        ]
        == "build6r-immutable-cutout-v1.1"
    )

    assert (
        metadata[
            "threshold"
        ]
        == 30
    )

    second_isolator = get_isolator(
        enabled=False,
        source_path=source,
        prefer_immutable=True,
        cache_root=cache,
    )

    with Image.open(
        source
    ) as image:
        second = (
            second_isolator
            .isolate(
                image
            )
        )

    assert (
        first.tobytes()
        == second.tobytes()
    )

    assert (
        second_isolator.name
        == "immutable_sha_cutout_cached"
    )


def test_existing_transparency_is_preserved(
    tmp_path,
):
    source = (
        tmp_path
        / "transparent.png"
    )

    image = Image.new(
        "RGBA",
        (30, 30),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(
        image
    )

    draw.rectangle(
        (8, 5, 22, 25),
        fill=(200, 100, 30, 255),
    )

    image.save(
        source,
        "PNG",
    )

    cache = (
        tmp_path
        / "cache"
    )

    isolator = get_isolator(
        enabled=False,
        source_path=source,
        prefer_immutable=True,
        cache_root=cache,
    )

    with Image.open(
        source
    ) as opened:
        original = (
            opened
            .convert(
                "RGBA"
            )
            .copy()
        )

        result = isolator.isolate(
            opened
        )

    assert (
        result.tobytes()
        == original.tobytes()
    )

    assert (
        isolator.name
        == "immutable_existing_alpha"
    )


def test_low_confidence_photo_falls_back_without_aggressive_masking(
    tmp_path,
):
    source = (
        tmp_path
        / "complex.png"
    )

    # Deliberately non-uniform border.
    image = Image.new(
        "RGB",
        (60, 60),
    )

    pixels = image.load()

    for y in range(
        60
    ):
        for x in range(
            60
        ):
            pixels[
                x,
                y,
            ] = (
                (x * 7) % 256,
                (y * 9) % 256,
                ((x + y) * 5) % 256,
            )

    image.save(
        source,
        "PNG",
    )

    isolator = get_isolator(
        enabled=False,
        source_path=source,
        prefer_immutable=True,
        cache_root=(
            tmp_path
            / "cache"
        ),
    )

    with Image.open(
        source
    ) as opened:
        original = opened.convert(
            "RGBA"
        )

        result = isolator.isolate(
            opened
        )

    assert (
        result.tobytes()
        == original.tobytes()
    )

    assert (
        isolator.name
        == "immutable_fallback_none"
    )


def test_render_pipeline_always_prefers_immutable_product_layer():
    source = inspect.getsource(
        pipeline.render_slide
    )

    assert (
        "BUILD6R_IMMUTABLE_PRODUCT_CUTOUT_SELECTION"
        in source
    )

    assert (
        "source_path=creative_input.source_image_path"
        in source
    )

    assert (
        "prefer_immutable=True"
        in source
    )

    assert (
        "composite_product("
        in source
    )


def test_algorithm_never_calls_generative_provider():
    source = inspect.getsource(
        ImmutableProductCutoutIsolator
    ).lower()

    forbidden = [
        "openai",
        "image_provider",
        ".generate(",
        ".edit(",
        "recreate_creative",
    ]

    for token in forbidden:
        assert token not in source


def test_cutout_confidence_calibration_keeps_conservative_bounds():
    """Build 6R v1.1 calibration fixes the verified Melano false negative
    without weakening the independent removed-area safety limits.
    """

    assert (
        ImmutableProductCutoutIsolator.MIN_BORDER_MATCH_RATIO
        == 0.60
    )

    assert (
        ImmutableProductCutoutIsolator.MIN_REMOVED_RATIO
        == 0.03
    )

    assert (
        ImmutableProductCutoutIsolator.MAX_REMOVED_RATIO
        == 0.92
    )

    assert (
        ImmutableProductCutoutIsolator.ALGORITHM_VERSION
        == "build6r-immutable-cutout-v1.1"
    )

