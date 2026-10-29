# Hanna direct multimodal delivery completion

This completes the V10 delivery path, not another renderer. V9 remains closed.
No live call, automatic activation, migration, environment change or infrastructure
work is performed. Request construction is not permission to spend.

## Preparation and identity

`prepare_delivery` accepts the existing canonical V10 package. It creates a new
ephemeral delivery package with identical approved facts/copy and a digest-linked
original package. Canonical campaign/direction/registry data are never changed.
Re-resolve canonical authority immediately before any future authorized live run.

`select_references` chooses the canonical source view first (existing master-source
provenance, then resolution and stable ID), the strongest owner-approved target
composition, and the canonical logo when required. Additional product angles or
style exemplars require explicit asset IDs from the same governed package. It
never fills the input count opportunistically. Counts are 1–3 PRODUCT_REFERENCE,
1–4 STYLE_REFERENCE and at most seven total. A logo is explicitly a STYLE_REFERENCE
with purpose `brand_identity`; it is not counted as another composition exemplar.
Approved reconstructed masters may be explicit supporting inputs, never the
primary real-photograph authority. Hashes are checked again during translation.

## Guide, crop and typography

`CompositionGuide` describes a 1024×1280 final canvas retained at native crop
`(0,128,1024,1408)` inside 1024×1536 generation. Every named region is in final
coordinates; add 128 to y for native placement. Product priority, headline,
supporting copy, factual callouts, CTA, logo, protected breathing space, quiet
zones and decorative zones are all prepared before the prompt is built.

The default mode is clean-space plus exact deterministic typography. Every real
copy field receives a prepared region included in the request's quiet zones.
These describe designed negative space, not blank UI rectangles. Missing fonts,
copy that does not fit and insufficient region inventory fail closed rather than
shrinking, rewriting or adding panels. Font IDs resolve through the caller's
approved local font map. An explicit model-integrated mode remains supported.

`crop_and_treat` checks native dimensions, takes the precomputed crop and applies
only the selected V10 text treatment. It never resizes/stretches or calls V9.
Canonical logo integration is requested from its real reference, without adding
a floating tile. Final product/copy/structural/visual QA remains mandatory through
`accept_delivery` and the existing V10.1 acceptance gate. A crop or overlay
invalidates QA bound to earlier pixels; the review must bind to the final package
and output hashes. Technical delivery is not visual acceptance.

## Existing provider boundary

`direct_images_edit_request` in the existing OpenAI provider emits the narrow
Images Edit multipart request. Numbered actual image bytes and their role/purpose
legend stay aligned. The unified prompt includes canonical facts/copy/prohibitions,
brand instructions, visual objective, product preservation and exact crop/regions.
Historical renderer-plan text is retained in package provenance but not treated
as executable art direction in the new prompt.

Settings are explicit: pinned Sunburst by default (alias also accepted), high,
1024×1536, opaque, n=1, partial_images=0, stream=false and PNG. Exactly one complete
image result is accepted; no retry, model switch or compositor fallback exists.

Official API schema verified on 2026-10-29:
https://developers.openai.com/api/reference/resources/images/methods/edit

## Truthful cost seam and blocked execution

`MultimodalCostEstimator` separates text input, image input and image output.
`CostComponent` distinguishes BOUND, ESTIMATE and UNRESOLVED. Only three supported
BOUND components can form a total maximum; unknowns remain null, not zero.

The current official output estimate is preserved for Sunburst high 1024×1536:
1,372 output tokens at $30/M = $0.04116. It is an **output-only estimate**, not a
whole-request ceiling. Source: the official image-generation guide calculator,
verified 2026-10-29. Unknown models/settings remain unresolved. No GPT Image 2.5
input-image token formula or caching discount is inferred.

Today image-input estimation is UNRESOLVED, so `compose_direct_creative` raises
before client dispatch. It also retains the existing hard-budget ledger gate.
A future authoritative estimator plugs into the cost seam without changing the
creative architecture; separate governed ledger admission remains required. No
caller quote, nominal $0.50 cap or output-only estimate bypasses that boundary.
The new seam does not replace the ledger or enable live execution.

Official estimate/rates:
https://developers.openai.com/api/docs/guides/image-generation

An external immutable debug artifact records the canonical prepared request,
image-role/hash inventory, prompt, crop, text/logo/product regions, model/settings
and unresolved costs without credentials or a live API call.
