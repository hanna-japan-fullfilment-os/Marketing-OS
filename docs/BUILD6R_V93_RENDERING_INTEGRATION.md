# V9.3 reference-directed rendering integration

The exact Hanna premium reference path now consumes the unchanged V9.1 scene
and V9.2 style through `build_premium_render_plan` before final composition.
The plan binds scene/style/geometry digests and the separate canonical product
layer digest. Altered plans, pixels or ownership fail closed.

`art_layer_adapter.gpt_image_2_art_request` is the narrow provider-specific
boundary. It produces a text-only, geometry-aware request using the existing
bounded GPT Image 2 contract. It neither constructs a provider nor dispatches
requests. It carries no approved copy, product artwork or logo image. Core
scene, style and rendering plans remain provider-neutral.

## Art ownership and order

Art owns the distant environment, optical/material atmosphere and surface
texture. Code owns product-specific halo, ambient/contact shadow, grounding
plane, selected light arcs/editorial rules, canonical product pixels, typography,
callout, CTA and brand. A lacquer texture motif is art-owned; code never draws it
again. Provider exclusions explicitly forbid code-owned motifs, product shadows,
halos, product packages, readable text, logo, CTA and factual badges.

Order is background -> midground support -> product -> foreground accents ->
typography/brand. Midground includes light-aligned support and grounding;
foreground accents are masked away from every nonzero product-alpha pixel.
All supporting effects reserve text/logo zones, keeping their sampled contrast
base intact. No destructive product relighting or AI reconstruction occurs.

The existing locked product crop/resize/placement is reconstructed and checked
against its trusted product-layer hash. New grounding is applied to the clean
art layer rather than to an old flattened product image. Source files and real
package pixels stay authoritative; opaque output pixels remain identical to the
approved deterministic resampling. Transparent edges blend with the new scene.

## Actual treatment rendering

HTML applies direct/tonal/veil/editorial text treatments, open/inset callout
rules, an integrated gold CTA band or editorial CTA rule, and transparent,
tonal or corner logo zones. Logo RGB/source remain unchanged. Actual CTA
foreground/surface values reach the existing measurement probe. No generic
white contrast fallback or default opaque text panel is introduced. Fonts,
text, boxes, line budgets and all 20 structural QA rules remain authoritative.
The template recipe identity advances to 1.5.0 for this rendering change.

## Callability and failure behavior

`render_slide` automatically selects V9 for verified Hanna references.
`SlideCreativeInput(premium_render_mode="v9")` requires that path and never
catches a failure to retry the legacy renderer. Other references keep V9.1/V9.2
behavior, and non-premium rendering stays legacy-compatible. Supplying static
art is sufficient for zero-cost engineering fixtures. Missing art uses the
existing deterministic brand background, never a provider or model fallback.

For governed V9.4 orchestration: resolve the existing scene/style; call the pure
render-plan builder with native art dimensions; obtain the text-only request
through the adapter; make any separately authorized call through the existing
budgeted provider; then pass the returned art as `generated_background` to the
normal pipeline with V9 explicitly required. Final contrast planning samples
the actual fitted art, and final composition is preceded by its bound render
plan. No further architecture patch or budget rewrite is required.

Render context persists scene, style, art prompt spec, render plan, layer
metadata and frozen QA geometry; enrichment preserves them. `debug_premium_render`
returns their JSON representation with no provider execution or acceptance claim.

V9.3 tests use synthetic art/products and local PNGs only. They prove engineering
integration, not a postable Hanna advertisement. Real cover and conditional
carousel acceptance remain exclusively V9.4. No provider dispatch is authorized
or performed here.
