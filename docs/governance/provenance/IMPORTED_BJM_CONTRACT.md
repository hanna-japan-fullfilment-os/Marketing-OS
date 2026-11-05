# Brazil Japan Marketplace — Canonical Engineering Contract

## Project Identity

Project code: BJM
Product: Brazil Japan Marketplace
Initial market: Brazilian community in Japan
Initial currency: JPY
Initial languages: Portuguese (`pt-BR`) and Japanese (`ja-JP`)
Primary consumer language: Portuguese
Database: Dedicated Supabase project in Tokyo
Payment platform: Stripe Connect
Frontend: Next.js + TypeScript
Package manager: npm workspaces
Database: PostgreSQL through Supabase
Deployment: Web/PWA first

This is a financial marketplace handling customer payments, merchant earnings, commissions, refunds, subscriptions and redeemable vouchers.

Correctness, security and traceability take precedence over coding speed.

## Product Mission

Create a marketplace for Brazilians in Japan to:

* discover businesses
* search local services
* view business pages
* follow businesses
* view merchant posts
* purchase services and offers
* receive vouchers
* redeem purchases in person
* book eligible services
* submit verified reviews

Businesses will be able to:

* create their business presence
* publish services
* create offers
* receive marketplace sales
* redeem vouchers
* manage customers
* view financial performance
* subscribe to paid tiers
* purchase marketing services
* advertise through the platform

Platform revenue may include:

1. Merchant subscriptions
2. Marketplace commissions
3. Marketing services
4. Sponsored placements
5. Campaign performance fees
6. Lead-generation fees

## Supabase Isolation

BJM MUST use a new dedicated Supabase project.

Do NOT use or modify:

* Athena OS
* Athena Business OS
* Beauty OS
* BeautyDNA
* Hanna
* any other existing Supabase project

Current BJM remote Supabase project reference: TBD.

Target region: Tokyo / `ap-northeast-1`.

Never invent the project reference.

Never run remote database operations until the correct BJM project has been explicitly verified.

## Repository Structure

Target:

```text
apps/
  marketplace/
  merchant/
  admin/

packages/
  ui/
  database/
  auth/
  payments/
  pricing/
  vouchers/
  i18n/
  validation/
  config/

supabase/
  migrations/
  functions/
  tests/
  seed.sql
  config.toml

docs/
  architecture/
  product/
  payments/
  security/

CLAUDE.md
PROJECT_STATE.md
README.md
```

Do not reorganize this architecture without documenting a clear reason.

## Build Discipline

Implement exactly ONE canonical build at a time unless explicitly authorized.

If the active build is:

`BJM-MVP-0001`

do not silently implement BJM-MVP-0002 or later features.

Future-compatible architecture is acceptable.

Future feature implementation is not.

## Before Every Build

Before modifying code:

1. Read `CLAUDE.md`.
2. Read `PROJECT_STATE.md`.
3. Check current Git branch.
4. Check Git status.
5. Inspect existing code.
6. Inspect existing migrations.
7. Search for existing functions/tables/components before creating new ones.
8. Confirm requested build scope.
9. Confirm required dependencies already exist.
10. Identify unrelated uncommitted changes.

Do not overwrite unexplained work.

Do not invent duplicate canonical objects.

## Git Rules

Use one branch per build.

Pattern:

```text
feature/bjm-mvp-0001-foundation
feature/bjm-mvp-0002-design-system
feature/bjm-mvp-0003-auth
```

Do not mix unrelated changes.

Do not commit secrets.

Do not force-push unless explicitly authorized.

## Database Changes

All canonical database changes must use version-controlled migrations.

Never make production schema changes only through the Supabase dashboard.

Never rewrite an already-applied production migration.

Create a new migration instead.

Canonical schemas:

```text
public
private
finance
```

## Authentication

Use Supabase Auth.

Do not create separate authentication systems for customers and merchants.

One user may be:

* consumer
* business owner
* business employee
* authorized platform operator

Authorization comes from memberships and roles.

## Merchant Authorization

Never trust client-supplied `business_id` as proof of ownership.

Merchant access must be derived from canonical business membership records.

Expected merchant roles:

```text
owner
admin
manager
reception
marketing
finance
voucher_only
```

## Row Level Security

RLS is mandatory for exposed tenant/customer data.

Never fix a problem by disabling RLS.

Never expose privileged Supabase credentials to browser code.

Client applications use public/publishable credentials.

Privileged credentials remain exclusively in trusted backend environments.

## Tenant Isolation

Merchant A must never access Merchant B:

* private orders
* customers
* finances
* unpublished content
* subscriptions
* marketing jobs
* private files

Customer A must never access Customer B:

* orders
* vouchers
* refunds
* bookings
* notifications
* private profile information

Cross-tenant isolation requires automated tests.

## Money

MVP currency is JPY.

Store money as integer yen.

Correct:

```text
6500
```

Incorrect:

```text
6500.00 stored as floating point
```

Never use floating-point arithmetic for financial calculations.

## Browser Trust Boundary

The browser is never authoritative for:

* price
* discount eligibility
* commission
* merchant net amount
* payment success
* refund completion
* payout completion
* voucher validity
* verified-review status

These must be calculated or validated by trusted backend/database logic.

## Merchant Plans

Initial canonical commercial model:

```text
Marketplace
¥0/month
15% transaction commission

Presença
¥4,980/month
12%

Crescer
¥14,800/month
9%

Pro
¥39,800/month
7%
```

These values must eventually be configurable database records.

Do not scatter them throughout application code.

## Financial Components

Keep these separate:

```text
gross_amount
discount_amount
marketplace_commission_rate
marketplace_commission_amount
campaign_fee_rate
campaign_fee_amount
processing_fee_allocation
fixed_platform_fee
merchant_net_expected
```

Never collapse every charge into one ambiguous commission field.

## Fee Precedence

Initial order:

```text
merchant override
>
campaign rule
>
merchant plan
>
platform default
```

Checkout calculations must be snapshotted.

Future fee changes must not alter historical transaction economics.

## Historical Immutability

Preserve historical:

* item title
* item price
* discount
* merchant plan
* applicable fee rule
* commission
* payment-related allocation
* campaign attribution
* expected merchant amount
* pricing engine version

Do not recalculate old orders using current merchant settings.

## Checkout

MVP rule:

One order = one merchant.

Do not implement a multi-merchant cart during MVP.

## Stripe Connect

Stripe Connect is the initial marketplace payment provider.

Merchant connected accounts use provider onboarding.

Do not store raw merchant bank credentials.

Provider/backend state determines onboarding and payment readiness.

A browser return URL does not prove success.

## Payments

Payment completion must come from trusted Stripe/API/webhook state.

Never issue a voucher solely because the browser reached `/success`.

Webhook processing must include:

* signature verification
* event ID uniqueness
* idempotency
* duplicate-event tolerance
* out-of-order-event tolerance
* failure state
* reconciliation capability

## Voucher Security

Voucher QR codes must use high-entropy opaque values.

Do not rely on sequential database IDs.

Redemption validates:

* voucher existence
* merchant
* location if restricted
* order
* payment state
* expiration
* cancellation
* refund status
* previous redemption

Voucher redemption must be atomic.

Two simultaneous redemption attempts must result in:

```text
1 success
1 already redeemed/failure
```

Never two successful redemptions.

## Refunds

Refunds are controlled workflows.

Expected states:

```text
requested
under_review
approved
processing
completed
rejected
failed
```

A completed refund must reconcile relevant payment, order, voucher, inventory and financial records.

## Financial Ledger

Financial history should use append-only/corrective journal principles.

Do not silently rewrite past financial entries.

Every accounting journal must balance.

## Reviews

`verified_purchase` is backend-controlled.

Clients may never declare themselves verified.

Verified review eligibility requires canonical qualifying transaction history.

## Entitlements

Plan features must eventually be centrally enforced.

Examples:

```text
MAX_SERVICES
MAX_MONTHLY_POSTS
ADVANCED_ANALYTICS
CUSTOMER_CRM
MULTI_LOCATION
STAFF_ACCOUNTS
MARKETING_CREDITS
AI_MARKETING
```

Frontend visibility is not security.

Backend enforcement is required.

## AI Boundary

AI may eventually:

* create marketing
* translate content
* recommend businesses
* suggest promotions
* summarize analytics

AI must never independently determine:

* payment success
* merchant payout
* refund completion
* voucher validity
* accounting truth

Financial authorization remains deterministic.

## Testing

Every build must add appropriate tests.

As applicable:

* unit tests
* database tests
* RLS tests
* integration tests
* end-to-end tests

Commerce functionality requires negative tests, not only happy paths.

## Validation

As applicable, run:

```text
npm run lint
npm run typecheck
npm test
npm run build
```

Also run relevant:

* database tests
* migration tests
* Supabase tests
* RLS tests
* Playwright tests

Never claim a command passed unless it actually ran.

## Completion Report

At the end of every build provide:

1. Build ID and title
2. Build status
3. Scope actually implemented
4. Files changed
5. Migrations created
6. Database objects created/changed
7. Production functions/components created/changed
8. Tests added
9. Exact validation commands executed
10. Validation results
11. Security/RLS effects
12. Financial/payment effects
13. Known issues
14. Out-of-scope work deliberately not implemented
15. Git branch/status
16. Commit status
17. Exactly one recommended next build

## PROJECT_STATE.md

After every completed build update `PROJECT_STATE.md`.

It must contain verified facts only.

Do not use it as a diary.

## Never

Never:

* disable RLS to solve errors
* trust frontend pricing
* trust frontend commissions
* trust frontend merchant ownership
* expose privileged credentials
* make canonical production database changes outside migrations
* mark payment successful from browser redirects
* issue duplicate vouchers
* permit non-atomic redemption
* modify historical pricing snapshots
* casually delete financial history
* store raw card information
* create multi-merchant MVP checkout
* implement future builds without authorization
* use AI for financial authorization
* hide failing tests
* claim tests ran when they did not
* invent duplicate database objects instead of inspecting existing code

## Engineering Preference

Prefer:

* explicit maintainable code
* deterministic financial logic
* small typed functions
* schema validation
* database constraints
* centralized authorization
* idempotent operations
* observable failures
* clear migrations

Avoid premature:

* microservices
* Kafka
* Elasticsearch
* Redis clusters
* complicated abstractions
* unnecessary dependencies

## Product Critical Path

Prioritize:

```text
merchant onboarding
→ services
→ offers
→ discovery
→ plans
→ pricing
→ Stripe
→ orders
→ payments
→ ledger
→ vouchers
→ redemption
→ reviews
→ refunds
→ merchant/admin operations
→ security QA
→ financial QA
→ pilot launch
```

## Current Build Roadmap

BJM-MVP-0001 Repository & Platform Foundation
BJM-MVP-0002 Design System & Application Shells
BJM-MVP-0003 Authentication & User Identity
BJM-MVP-0004 Japan Geography & Business Categories
BJM-MVP-0005 Merchant Registration & Business Foundation
BJM-MVP-0006 Merchant Verification & Admin Approval
BJM-MVP-0007 Merchant Services & Media
BJM-MVP-0008 Offers, Promotions & Inventory
BJM-MVP-0009 Business Pages & Consumer Discovery
BJM-MVP-0010 Merchant Posts, Favorites & Following
BJM-MVP-0011 Merchant Plans & Subscription Entitlements
BJM-MVP-0012 Commission & Pricing Engine
BJM-MVP-0013 Stripe Connect Merchant Onboarding
BJM-MVP-0014 Orders & Immutable Pricing Snapshots
BJM-MVP-0015 Marketplace Checkout
BJM-MVP-0016 Payment Webhooks & Reconciliation
BJM-MVP-0017 Financial Ledger
BJM-MVP-0018 QR Voucher System
BJM-MVP-0019 Atomic Voucher Security
BJM-MVP-0020 Verified Reviews & Reputation
BJM-MVP-0021 Refunds, Cancellations & Disputes
BJM-MVP-0022 Merchant Dashboard
BJM-MVP-0023 Merchant Financial Dashboard
BJM-MVP-0024 Staff Roles & Merchant Permissions
BJM-MVP-0025 Admin Operations Center
BJM-MVP-0026 Audit & Operational Security
BJM-MVP-0027 Marketing Jobs
BJM-MVP-0028 Sponsored Marketplace Placement
BJM-MVP-0029 Basic Merchant CRM
BJM-MVP-0030 Leads & Quote Requests
BJM-MVP-0031 Basic Booking
BJM-MVP-0032 Notifications
BJM-MVP-0033 Portuguese/Japanese Localization
BJM-MVP-0034 Marketplace Analytics
BJM-MVP-0035 Security & RLS Audit
BJM-MVP-0036 Payment & Financial QA
BJM-MVP-0037 UX & Mobile Polish
BJM-MVP-0038 Pilot Merchant Onboarding Tools
BJM-MVP-0039 Closed Beta
BJM-MVP-0040 Public Pilot Launch

## Current Authorized Build

Only:

**BJM-MVP-0001 — Repository & Platform Foundation**

Do not begin BJM-MVP-0002 until BJM-MVP-0001 passes its exit gate and is explicitly authorized.


