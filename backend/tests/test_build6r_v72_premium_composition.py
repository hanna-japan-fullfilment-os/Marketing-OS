"""Synthetic, provider-free geometry and HTML contract tests, not visual acceptance."""
from dataclasses import replace
import json

import pytest

from app.schemas.creative_director import ReferenceTarget
from app.services.creative.composition import Box, LayoutSpec, resolve_composition, union_area
from app.services.creative.templates import Feature, TemplateContext, get_template


def context(**changes):
    target = ReferenceTarget.model_validate(dict(
        reference_id="approved-generic-fixture", sha256="a"*64, role="TARGET",
        source="OWNER_APPROVED_TARGET", grammar=dict(
            typography="sans", headline_scale=.09, headline_position="upper_left",
            supporting_copy_position="left_column", callout_treatment="gold",
            density="dense", background="dark_cinematic", material="glossy",
            lighting="dramatic_rim", depth="layered", negative_space="modular",
            color_behavior="high_contrast", hierarchy="headline_hero_callouts")))
    defaults = dict(width=1080, height=1350, composited_image_data_uri="data:image/png;base64,",
                    reference_target=target, headline="Conheça", font_family="Arial, sans-serif",
                    secondary_font_family="Arial, sans-serif", slide_role="premium_hook")
    return TemplateContext(**(defaults | changes))


def product():
    return Box(572, 650, 465, 630)


@pytest.mark.parametrize("role,profile", [
    ("cover", "hero"), ("product_introduction", "hero"), ("feature_detail", "feature"),
    ("formula_proof", "specification"), ("routine_context", "context"),
    ("brand_close_cta", "close"),
])
def test_profiles_are_deterministic_and_serializable(role, profile):
    ctx = context(slide_role=role, cta="Saiba mais")
    a = resolve_composition(ctx, product())
    b = resolve_composition(ctx, product())
    assert a == b and a.digest == b.digest
    assert LayoutSpec.from_dict(json.loads(json.dumps(a.to_dict()))).digest == a.digest
    assert a.template == profile and a.product == product()
    assert a.logo.x == 864 and a.margin == 43.2
    assert a.cta.width <= .44*a.width


def test_rich_content_roles_preserve_every_existing_field():
    ctx = context(eyebrow="Coleção", intro="Conheça a coleção", body="Saiba mais",
                  features=[Feature(icon="✓", title="7 máscaras", subtitle="150 mL")],
                  callout_label="Conteúdo", callout_value="7 máscaras", cta="Saiba mais",
                  bottom_features=["Tecido"], trust_badges=["Marca"], badge_text="Coleção",
                  disclaimer="Imagens meramente ilustrativas.")
    spec = resolve_composition(ctx, product())
    roles = {r.key:r for r in spec.roles}
    assert roles["headline"].role == "HEADLINE"
    assert roles["body"].role == "SUPPORTING_COPY"
    assert roles["feature_0"].role == roles["callout"].role == "FACT_CALLOUT"
    assert roles["cta"].role == "CTA" and not spec.sparse
    assert set(roles) == {"eyebrow", "headline", "intro", "body", "feature_0", "callout",
                          "cta", "badge", "bottom_features", "trust_badges", "disclaimer"}
    assert roles["feature_0"].text == "✓\n7 máscaras\n150 mL"
    html = get_template("feature_showcase").build_html(replace(ctx, composition_spec=spec))
    assert 'data-composition-role="headline"' in html
    assert '.text-block' not in html and 'data-composition-role="callout"' in html
    assert "7 máscaras" in html and "150 mL" in html
    assert 'id="composition-spec"' in html and spec.digest in html


@pytest.mark.parametrize("headline", ["Descubra", "Máscara japonesa: informação, ação e proteção.",
                                       "Conheça\na coleção", "Água, essência e atenção!", "<script>ação</script>"])
def test_portuguese_is_preserved_without_silent_shortening(headline):
    ctx = context(headline=headline)
    spec = resolve_composition(ctx, product())
    assert next(r.text for r in spec.roles if r.key == "headline") == headline
    assert spec.sparse
    html = get_template("feature_showcase").build_html(replace(ctx, composition_spec=spec))
    assert '<script>ação</script>' not in html


def test_sparse_roles_do_not_fabricate_copy_or_cta():
    spec = resolve_composition(context(features=[Feature(title="7 máscaras")]), product())
    assert [(r.key,r.text) for r in spec.roles] == [("headline","Conheça"), ("feature_0","7 máscaras")]
    assert not spec.cta_required
    assert spec.product == product()


def test_missing_close_cta_is_required_but_never_invented():
    spec = resolve_composition(context(slide_role="brand_close_cta"), product())
    assert spec.cta_required and not any(r.key == "cta" for r in spec.roles)


def test_prepared_right_column_is_preserved_not_automatically_swapped():
    ctx = context()
    target = ctx.reference_target.model_copy(update={"grammar":ctx.reference_target.grammar.model_copy(
        update={"headline_position":"upper_right", "supporting_copy_position":"right_column"})})
    spec = resolve_composition(replace(ctx, reference_target=target, body="Informação"), product())
    assert next(r for r in spec.roles if r.key == "headline").box.x > 500
    assert next(r for r in spec.roles if r.key == "body").box.x > 500
    assert spec.product == product()  # Any actual collision must fail QA.


def test_profiles_have_distinct_geometry_and_order():
    ctx = context(body="Informação", features=[Feature(title="7 máscaras"), Feature(title="150 mL")])
    feature = resolve_composition(replace(ctx, slide_role="feature_detail"), product())
    proof = resolve_composition(replace(ctx, slide_role="formula_proof"), product())
    assert feature.roles[1].key == "body" and proof.roles[1].key == "feature_0"
    assert feature.roles[1].box != proof.roles[1].box
    close = resolve_composition(replace(ctx, slide_role="brand_close_cta", cta="Saiba mais"), product())
    assert close.cta.height > feature.cta.height


@pytest.mark.parametrize("template", ["feature_showcase", "premium_product_hero"])
def test_legacy_template_input_remains_supported(template):
    ctx = context(reference_target=None)
    html = get_template(template).build_html(ctx)
    assert "Conheça" in html and "composition-spec" not in html


def test_union_area_does_not_double_count_overlap():
    assert union_area([Box(0,0,10,10), Box(5,0,10,10)]) == 150


@pytest.mark.parametrize("args", [(0,0,0,1), (0,0,1,-1), (float('nan'),0,1,1)])
def test_invalid_geometry_rejected(args):
    with pytest.raises(ValueError):
        Box(*args)


def test_structural_counter_and_prepared_left_product_are_preserved():
    ctx = context(slide_number=1,total_slides=6)
    target = ctx.reference_target.model_copy(update={"grammar":ctx.reference_target.grammar.model_copy(
        update={"headline_position":"upper_right","supporting_copy_position":"right_column"})})
    p = Box(43.2,650,465,630)
    spec = resolve_composition(replace(ctx,reference_target=target),p)
    assert next(r.text for r in spec.roles if r.key == "slide_marker") == "1/6"
    assert not p.intersects(spec.quiet) and spec.product == p


def test_other_reference_classes_keep_legacy_rendering_contract():
    from app.services.creative.composition import uses_premium_composition
    ctx = context()
    assert uses_premium_composition(ctx.reference_target)
    raw = ctx.reference_target.model_dump()
    raw["grammar"]["background"] = "light"
    assert not uses_premium_composition(raw)


def test_pipeline_resolves_before_render_and_preserves_context_on_enrichment(tmp_path):
    from test_creative import _repair_plan, _repair_input, _repair_finish, _RepairRenderer
    from app.services.creative.pipeline import render_slide, build_render_context_path, persist_render_context
    plan = _repair_plan(tmp_path)
    ref = plan.reference_assets[0]
    target = context().reference_target.model_copy(update={"reference_id":ref.asset_id,"sha256":ref.sha256})
    plan = plan.model_copy(update={"visual_brief":json.dumps({"REFERENCE_TARGET":target.model_dump()})})
    inp = replace(_repair_input(plan),reference_target=target)
    renderer = _RepairRenderer()
    output = tmp_path/"synthetic.png"
    result = _repair_finish(render_slide(inp,output_path=output,renderer=renderer))
    assert "composition-spec" in renderer.html
    # Old fake renderer lacks real observations and cannot authorize premium QA.
    assert not result.qa.passed and result.qa.composition["score"] is None
    before = json.loads(build_render_context_path(output).read_text(encoding="utf-8"))
    persist_render_context(slide_output_path=output,creative_direction={},visual_base=None,visual_base_kind="none")
    after = json.loads(build_render_context_path(output).read_text(encoding="utf-8"))
    assert after["composition_spec_sha256"] == before["composition_spec_sha256"]
    assert after["composition_spec"] == before["composition_spec"]
    assert after["slide_contract"] == plan.model_dump()
