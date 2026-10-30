# V12.4 claims evidence and benefit-brief gate

Creative production remains paused. No artwork, renderer changes, migration,
campaign mutation or source-asset approval is part of this build. Slide 1's
historical owner approval and its artifact are preserved. This build does not
repair campaign-wide approval invalidation from a later brief change.

## Research and review

The JSON matrix in `backend/app/data/LULULUN_HYDRA_EX_CLAIM_EVIDENCE_MATRIX.json`
is the exact-product reviewed wording projection for EX 1FS, JAN 4580794010660.
It links all eight pre-existing V3.45 claim IDs where applicable. It does not
replace or write the existing product evidence registry. New researched wording
is not silently inserted into the canonical product/campaign database.

Manufacturer product/launch materials and exact package identity are primary.
The official EX formula, sensory sheet design, morning/evening use, quantity,
directions and qualifications were checked. Adjacent CX/CICA, PD/PDRN and other
variants supply no evidence for EX. Ingredient science cannot establish efficacy
of this finished product; no independent exact-product clinical study dossier was
established by this research. Elasticity/age-related positioning, historical
comparisons, awards and statistics remain NEEDS_REVIEW. No generic ingredient
paper is used to manufacture approval of regeneration or whitening claims.

Anvisa RDC 907/2024, especially arts. 5, 8, 9 and 12, provides the reviewed
Brazilian cosmetic-risk context: retain substantiation, avoid misleading wording
and therapeutic attribution. This does not certify Brazilian product registration
or represent an Anvisa advertising authorization. The matrix's source notes link
the consolidated text. The older Anvisa labeling FAQ is discovery context only;
it is not presented as the current regulation.

The consolidated RDC 529/2021 Annex entry 416 also prohibits human-origin cells,
tissues and products in cosmetics. The manufacturer's declared human-derived
exosome ingredient creates an unresolved exact-product Brazil assessment issue.
Presence is verified, but its marketing record is NEEDS_REVIEW and excluded from
the creative library. `brazil_market_review_status=REVIEW_REQUIRED` independently
blocks CREATIVE_READY even if the owner approves the copy library. Documented
qualified product assessment is required; owner copy approval alone cannot clear
this gate. This is an identified regulatory conflict needing assessment, not a
claim that this build adjudicated the SKU's legal status.

Each matrix record contains the source meaning, publisher/type/reference, scope,
classification, PT-BR versions, qualifier, prohibited variants, review/language
status, priority and notes. Statements have exactly one class. APPROVED_DIRECT,
APPROVED_WITH_QUALIFIER and FACT_ONLY can enter the filtered review library;
NEEDS_REVIEW and PROHIBITED_UNSUPPORTED cannot. Natural pt-BR has been editorially
reviewed; this is not described as an independent human native-speaker
certification. The complete library and slide proposals still require owner
review before activation (`owner_library_review_status=PENDING`).

## Gate behavior

`marketing_claims.load_library(product_id)` checks exact identity and all eleven
research categories. `resolve_copy` matches only reviewed exact wording variants,
allowing capitalization/Unicode/whitespace normalization, never free paraphrase.
It returns field-to-claim-ID bindings. It does not let a creative model invent an
ID or decide that an ingredient proves a benefit.

`bind_handoff` requires owner library approval and binds the canonical handoff.
`validate_brief` verifies every visible field against IDs, requires mandatory
qualifiers in visible copy, and requires a benefit hierarchy. A usage-only brief
fails when approved benefits exist. Headings such as Luminosidade cannot appear
without their approved dryness-qualified supporting copy on the same slide.
Ingredient facts stay facts. No product efficacy is inferred from ceramides,
collagen, EGF, glutathione, arbutin or exosomes.

`build_campaign_handoff` binds through this gate; `export_handoff` independently
rechecks it before creating output directories or files. Drafts, missing IDs,
wrong SKU, unapproved translations, missing qualifiers, stale library hashes and
forged CREATIVE_READY flags fail closed. Other products/locales need their own
reviewed library; there is no English or adjacent-variant fallback. No source
hash or review marker alone replaces recomputation of approved wording/IDs.

The handoff contains APPROVED_COPY, APPROVED_CLAIM_IDS, MANDATORY_QUALIFIERS,
PROHIBITED_WORDING (in prohibited_elements), BENEFIT_HIERARCHY and a filtered
approved library. It does not export unresolved matrix research as approved
creative instructions. Raw canonical V3.45 facts remain provenance context,
explicit instructions constrain rendering to approved visible copy.

The lexical deny layer is an additional filter, not a semantic NLP classifier.
Unknown paraphrases are blocked by the closed approved-wording allowlist. No
statistical/comparative wording is approved in this release; approving it later
requires exact product, metric, population, comparator, period, geography and
study/source review, not just a percentage printed in a blog or old launch image.

## Owner-review deliverables and proposed content architecture

`approved_library(library)` derives the categorized creative-facing review
library. `proposed_content_plan(library)` produces complete structured briefs for
slides 2–6 without changing campaign data. Validation evidence exports both as
JSON/Markdown outside the repository for owner review.

| Slide | Proposed role | Message and support |
| --- | --- | --- |
| 2 | Product benefits and formula | Hydration/radiance headline; hydration, softness and full dryness-qualified luminosity; formula facts |
| 3 | Sheet technology and softness | Soft touch; Melty Feel Sheet; three-layer construction |
| 4 | Formula without efficacy inference | Moisturizing context; glutathione/arbutin/AP/NP; vitamin-C and hyaluronic derivatives as presence facts |
| 5 | Moisturizing routine | Hydration leads; supported morning/evening, toner replacement and application/aftercare guidance |
| 6 | Benefit, pack and brand close | Moisturizing reminder; exact seven-sheet/150mL pack; existing brand-close/CTA wording |

Every proposed slide includes a benefit; the usage slide is no longer mechanical
instructions alone. Do not force an unsupported elasticity claim into a spare
slot. Slide 1 is not replanned. These proposals do not replace live SlidePlans,
write owner decisions, approve images or bypass V3.45 asset/claim provenance.

After owner review, activation needs the normal governed data/brief process.
Changing a campaign snapshot still requires resolving its existing approval
invalidation contract before production can resume. V12.4 does not silently
reactivate V12.3 or authorize another image generation.

## Validation

Tests cover complete primary provenance, classifications, qualifiers, ingredient
vs efficacy, therapeutic/comparative rejection, unapproved translations, exact
approved language, missing IDs, benefit-led readiness and exported prohibitions.
V12.1 fixtures are explicitly updated to use an isolated reviewed exact-SKU
catalog; they do not mark the production catalog owner-approved. Existing intake,
duplicate, revision, tamper and publishing tests continue unchanged in behavior.
No existing failing asset-hash fixture is changed, skipped or reclassified as a
pass. Canonical DB, isolated accepted artwork state, .env and source image hashes
are verified unchanged during validation. No full application startup occurs.
