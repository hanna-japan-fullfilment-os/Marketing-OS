
import inspect

from app.services.creative import templates


def _v21_source():
    source = inspect.getsource(
        templates._build_feature_showcase
    )

    marker = source.index(
        "BUILD6R_FINAL_OFFLINE_VISUAL_POLISH_V21"
    )

    return source[
        marker:
    ]


def test_v21_final_visual_polish_is_installed():
    source = inspect.getsource(
        templates._build_feature_showcase
    )

    assert (
        "BUILD6R_FINAL_OFFLINE_VISUAL_POLISH_V21"
        in source
    )


def test_sparse_hero_no_longer_uses_dark_local_panel():
    source = _v21_source()

    assert (
        ".layout-sparse_hero .text-block"
        in source
    )

    assert (
        "background: transparent;"
        in source
    )

    assert (
        "border-left:"
        in source
    )

    assert (
        "rgba(32,29,23"
        not in source
    )


def test_sparse_hero_returns_to_dark_editorial_typography():
    source = _v21_source()

    assert (
        ".layout-sparse_hero .headline"
        in source
    )

    assert (
        "color: {ctx.text_color};"
        in source
    )

    assert (
        "text-shadow: none;"
        in source
    )


def test_feature_commerce_footer_moves_into_message_column():
    source = _v21_source()

    assert (
        ".layout-feature_commerce .commercial-footer"
        in source
    )

    assert (
        "top: 51%;"
        in source
    )

    assert (
        "bottom: auto;"
        in source
    )

    assert (
        "width: 35%;"
        in source
    )


def test_feature_commerce_cta_is_prominent_and_not_pill_ui():
    source = _v21_source()

    assert (
        ".layout-feature_commerce .cta-pill"
        in source
    )

    assert (
        "background: {ctx.accent_color};"
        in source
    )

    assert (
        "border-radius: 0;"
        in source
    )

    assert (
        "font-size:"
        in source
    )


def test_v21_is_css_only():
    source = _v21_source()

    forbidden = [
        "recreated_image",
        "openai",
        "image_provider",
        "source_image_path",
        "composite_product(",
        "get_isolator(",
    ]

    for token in forbidden:
        assert token not in source
