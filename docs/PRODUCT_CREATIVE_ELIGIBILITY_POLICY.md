# Product creative eligibility

This rule applies across brands/products and creative formats. Commercial
registration, import eligibility, unresolved market review, and pending Brazil
clearance do not independently block creative use. A current, confirmed Brazilian
ingredient prohibition applicable to the exact formula and product use blocks
creation, with an ingredient-specific warning and source. Missing or uncertain
evidence allows creative use with a warning; it is not a declaration of safety,
ingredient permission, or permission to sell/import/publish.

The shared service is `app.services.product_creative_eligibility`. It is checked
by campaign stages, creative package validation, prepared multimodal/direct/locked
scene generation, and premium handoff binding/export. Prepared objects are
rechecked immediately before provider calls so an old package cannot silently
bypass a later prohibition. Existing copy, evidence, owner review, budget,
identity and human visual-approval gates remain independent and unchanged.

`GET /api/products/{product_id}/creative-eligibility` exposes the current decision
and warnings. Canonical creative packages and exported handoffs include the
decision/warnings; campaign-stage warnings also appear in application logs.
There is no new frontend banner in this change.

Reviewed ingredient assessments live in
`backend/app/data/PRODUCT_CREATIVE_ELIGIBILITY.json`. This starts empty: no real
product has been declared permitted or prohibited by this change. There is no
automatic internet/ingredient screening and no paid/provider request. Add an
assessment only after a separately verified ingredient determination: exact
product ID, ingredient, official source URL/excerpt, reviewer, review/expiry
dates, exact-formula match, and confirmation that the prohibition applies to
the product's actual use. Ingredient-name similarity, brand-wide inheritance,
registration status and an unconfirmed concern are insufficient.

Only current `CONFIRMED_PROHIBITED` records block. `UNRESOLVED`, expired and future
records warn without declaring a prohibition. A current prohibition cannot be
cancelled merely by adding an unresolved record. Update/review its evidence
explicitly. Malformed policy data is an operational error, never automatic
clearance or an ingredient prohibition finding.

No database migration, `.env` change, canonical DB write or claim-library rewrite
is needed. Historical regulatory findings and claim restrictions remain evidence;
the old blanket market-clearance precondition is no longer a creative-use gate.
