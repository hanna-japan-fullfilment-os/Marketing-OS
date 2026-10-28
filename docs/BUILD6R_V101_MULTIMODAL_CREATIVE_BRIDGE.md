# Hanna multimodal creative director bridge

V9.4 remains FAIL and closed. This bridge does not import or invoke its renderer.
It exposes a separate service boundary, with no automatic campaign activation,
approval, retries, paid fallback, registry changes or database writes.

## Canonical handoff

`build_hanna_creative_package` reads the existing approved campaign plans and
V3.45 evidence using `validate_slide_provenance` and the verified-facts resolver.
It carries the exact visible-copy contract and structural slide marker. Actual
source photography, existing approved master (with reconstruction provenance),
owner-approved references and canonical logo are hash-verified image inputs.
Additional angles can be supplied as explicit, individually governed source
image records. Permission on one image never authorizes a sibling image.

The immutable provider-neutral package includes product/category/role, locale,
channel, objective, exact dimensions/aspect, CTA, brand instructions, prohibitions,
claim provenance and every supplied image hash. Reference text is never claim
authority. The package digest changes with copy, permissions, assets or direction.
Handoff snapshots must be re-resolved before future live execution if canonical
campaign data or approvals may have changed; a snapshot is not permanent authority.

## Supported provider translation

The existing OpenAI provider is the only SDK boundary. `creative_director_request`
uses Responses with actual `input_image` data URIs, caller-configured director and
image models, the image-generation tool and one forced tool call. No Custom GPT
endpoint or hidden Custom GPT instructions are assumed. The reusable instruction
layer expresses the owner's supplied art direction, not extracted private prompts.

For a controlled edit, the prepared base is first, with source and reference
images following. The alpha-PNG mask must match base dimensions and is supplied
as `input_image_mask`. Masking is guidance, never proof of unchanged packaging.
Each explicit edit is a new complete, independently budgeted request; no hidden
multi-turn loop or automatic retry is implemented.
Native output must match the requested dimensions and final aspect. When needed,
the entire artwork is resampled (for example 1088×1360 to 1080×1350), without crop
or package reconstruction. QA binds to the final pixels after this operation.

API contract verified against official documentation on 2026-10-28:

- https://developers.openai.com/api/docs/guides/tools-image-generation
- https://developers.openai.com/api/reference/resources/responses/methods/create
- https://developers.openai.com/api/docs/guides/image-generation

## Budget and activation gate

**No live requests are admitted in V10.1.** The existing ledger cannot yet prove
an authoritative maximum for every text-input, image-input and image-output cost
in this new workflow. `compose_creative` and `review_creative` fail before dispatch,
including if a caller provides a dollar cap. The non-strict Responses ledger also
rejects image-generation tools rather than treating them as text-only requests.
There is no new guessed price, bypass flag or second ledger. Existing V5 hard
budget behavior is preserved.

The request translator, decoder and QA orchestration are implemented and tested
offline. Removing the activation gate requires separately governed cost-bound
evidence and implementation; V10.2 authorization alone cannot bypass it. Model IDs
must be supported for the chosen Responses/tool combination at that time.

## Text, product and visual acceptance

Mode A lets the model integrate canonical marketing text; independent final QA
must transcribe every field exactly. Unicode NFC and whitespace normalization
are allowed; case, accents, wording and numbers cannot be silently corrected.

Mode B requests a clean scene with prepared negative space and no marketing text.
`overlay_canonical_copy` draws exact typography directly with approved local fonts.
It rejects missing fonts, overlap, out-of-bounds regions and copy that does not fit.
It never draws a rectangle, shortens copy or creates a panel fallback. The final
overlaid image requires a new whole-image review; a pre-overlay pass is stale.

`CreativeReview` reuses the existing product-fidelity schema and requires explicit
major-element, component and variant matches. Color, shape, labels, closure,
proportions and distinctive marks must all match. Uncertainty rejects the image.
The review includes actual sources, references, logo and candidate, and is bound
to both package and output hashes. No clipping/overlap and valid geometry are
necessary but insufficient: cohesion, product integration, reference style,
absence of disconnected cards, logo/type integration and premium polish must
each pass. A generated attractive wrong product cannot be accepted.

Only `store_accepted_asset` can persist an accepted result through this service;
it validates the complete review and creates the destination exclusively. It
does not approve a campaign or write a registry/database record. The caller owns
the authorized output path. Synthetic test reviews are never live acceptance.

The external `HANNA_CREATIVE_PACKAGE_DEBUG.json` is a dry-run handoff: local paths,
hashes, authority, instructions and planned API fields are inspectable. Actual
API translation reads and embeds the image bytes, not paths as a substitute.
