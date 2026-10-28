# V9.2 Hanna premium design system

`premium_design.py` resolves a provider-neutral styling companion to the V9.1
scene. It binds both scene and geometry digests and cannot change approved copy,
fonts, type size, line budgets, placement, asset permission or QA policy.
Only the exact approved Hanna reference ID/hash pairs select it in the pipeline.
Other reference classes retain V9.1 behavior.

## Authority and vocabulary

The preserved V7/V8 target (072e9126...) and benchmark (2db6f2f...) support
gold editorial rules, violet optical glass, lacquer grounding, restrained light
arcs, specular accents and layered backgrounds. They supply visual rules only;
no product pixels, efficacy claims, awards or ranking language are imported.

Canonical brand roles are cream #F4EFE7, charcoal #181716 and gold #B99252.
Violet/lavender roles come from the preserved V8 approved palette. Muted text
reuses cream; no extra swatch is invented. The optional matcha role is inactive
because no approved matcha swatch exists in canonical data.

The catalogs contain four text-support variants, three logo variants, three
lighting presets, three grounding variants, two depth languages, three motifs,
four materials, two CTA treatments and three factual-callout treatments.
The four existing archetypes have explicit compatibility sets. Category hints
change only restrained material/lighting choices, never the brand core. Unknown
categories use the core, not fabricated category styling.

## Deterministic selection and safeguards

Opaque product pixels supply a bounded 64x64 nearest-sample histogram (alpha
>=128, 16-level RGB bins, deterministic tie breaking). It is an observable color
signal, not generative analysis, and does not alter product pixels.

Actual per-role scene samples choose light-on-dark or dark-on-light text. Mixed
zones may use bounded translucent charcoal support, never an opaque white panel.
Frozen actual-render QA still controls contrast and overflow. Sampled contrast
is a styling input, not proof that every future background pixel is safe.
Existing approved headline gradient/keyline paint remains authoritative.

Typography roles retain geometry, fonts, minimum sizes and line budgets. Text
and canonical logo transparency integrate through V9.1. No logo recoloring or
new branding is allowed. Logo-zone contrast is a tonal planning recommendation;
it does not claim a perceptual contrast score for every preserved logo pixel.

At most two decorative motifs (one for sparse scenes), two accent colors and
two surface treatments may be active. Shared axes, stroke width, opacity steps,
shadow vocabulary and logo/CTA relationships constrain cohesion. Invalid
identities, stale styles, raised limits or incompatible selections fail closed.

Text colors/support are consumed by the existing HTML path. Lighting, grounding,
depth, decorative geometry and physical material treatment remain resolved
design intent for V9.3, not photorealistically rendered effects in this build.
CTA and callout vocabulary does not add words when an approved role is absent.

## Inspection and persistence

`debug_premium_scene(scene, style)` returns JSON-ready scene, style, treatment
IDs, palette, vocabulary, lighting, grounding and cohesion. The pipeline stores
the companion and its digest beside the unchanged scene/layout contracts;
render-context enrichment preserves them. The JSON debug output makes no visual
acceptance claim. Tests use synthetic fixtures, including measured 1/2/3-line
callouts; there is no provider call or final campaign cover acceptance.
