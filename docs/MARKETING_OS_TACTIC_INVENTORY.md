# Marketing OS tactic inventory — V12.8

Source of truth: `backend/app/data/strategy_library.py` seeds CampaignStrategyType by stable key; runtime selection uses Campaign.strategy_type_id. `backend/app/data/campaign_archetypes.py` supplies visual archetypes. Existing operational grounding/underuse selection remains in orchestrator.py. No tactic seed changes.

64 canonical tactic definitions across 8 families; 10 distinct visual archetypes. Stable source keys below are tactic identifiers; generated database UUIDs are workspace-specific and are not invented.

| Canonical key | Name | Family | Product scope |
|---|---|---|---|
| guerrilla_marketing | Guerrilla Marketing | ATTACK | either |
| counter_marketing | Counter-Marketing | ATTACK | either |
| price_attack | Price Attack | ATTACK | single |
| competitor_comparison | Competitor Price Comparison | ATTACK | single |
| trend_jacking | Trend-Jacking | ATTACK | single |
| newsjacking | Newsjacking | ATTACK | single |
| anti_ad | Anti-Ad Campaign | ATTACK | either |
| influencer | Influencer Campaign | ACQUIRE | either |
| micro_influencer | Micro-Influencer Campaign | ACQUIRE | either |
| giveaway | Giveaway | ACQUIRE | multi |
| viral_campaign | Viral Campaign | ACQUIRE | single |
| referral | Referral Campaign | ACQUIRE | either |
| ugc_campaign | UGC Campaign | ACQUIRE | multi |
| meme_campaign | Meme Campaign | ACQUIRE | single |
| quiz_campaign | Quiz Campaign | ACQUIRE | multi |
| paid_ads | Paid Ads | ACQUIRE | single |
| discovery_campaign | Discovery Campaign | ACQUIRE | multi |
| interactive_campaign | Interactive Campaign | ACQUIRE | multi |
| flash_sale | Flash Sale | CONVERT | multi |
| scarcity_campaign | Scarcity Campaign | CONVERT | single |
| fomo_campaign | FOMO Campaign | CONVERT | single |
| bundle_campaign | Bundle Campaign | CONVERT | multi |
| upsell_campaign | Upsell Campaign | CONVERT | single |
| cross_sell_campaign | Cross-Sell Campaign | CONVERT | multi |
| limited_edition_campaign | Limited Edition Campaign | CONVERT | single |
| countdown_campaign | Countdown Campaign | CONVERT | single |
| social_proof_campaign | Social Proof Campaign | CONVERT | either |
| abandoned_cart_campaign | Abandoned Cart Campaign | CONVERT | either |
| problem_solution_campaign | Problem/Solution Campaign | CONVERT | multi |
| before_after_campaign | Before/After Campaign | CONVERT | single |
| personalization_campaign | Personalization Campaign | CONVERT | either |
| loyalty_campaign | Loyalty Campaign | RETAIN | either |
| vip_campaign | VIP Campaign | RETAIN | either |
| win_back_campaign | Win-Back Campaign | RETAIN | either |
| reactivation_campaign | Reactivation Campaign | RETAIN | either |
| subscription_campaign | Subscription Campaign | RETAIN | multi |
| customer_appreciation | Customer Appreciation | RETAIN | either |
| personalized_offers | Personalized Offers | RETAIN | either |
| storytelling_campaign | Storytelling Campaign | BRAND | single |
| cultural_campaign | Cultural / Seasonal Japan Campaign | BRAND | multi |
| behind_the_scenes | Behind-the-Scenes | BRAND | multi |
| founder_campaign | Founder Campaign | BRAND | either |
| japan_experience | Japan Experience Campaign | BRAND | multi |
| transparency_campaign | Transparency Campaign | BRAND | either |
| educational_campaign | Educational Campaign | BRAND | single |
| shock_curiosity_campaign | Shock/Curiosity Campaign | BRAND | single |
| localization_campaign | Localization Campaign | BRAND | single |
| product_drop | Product Drop | HYPE | either |
| launch_campaign | Product Launch | HYPE | either |
| restock_campaign | Restock Campaign | HYPE | single |
| mystery_campaign | Mystery Campaign | HYPE | single |
| early_access | Early Access | HYPE | either |
| secret_drop | Secret Drop | HYPE | single |
| event_campaign | Event Campaign | HYPE | multi |
| contest_campaign | Contest | COMMUNITY | multi |
| gamification_campaign | Gamification | COMMUNITY | either |
| community_challenges | Community Challenges | COMMUNITY | either |
| customer_voting | Customer Voting | COMMUNITY | multi |
| product_selection | Product Selection Campaign | COMMUNITY | multi |
| ambassador_campaign | Ambassador Campaign | COMMUNITY | either |
| competitor_counterattack | Competitor Counterattack | DEFENSE | either |
| price_match_response | Price Match Response | DEFENSE | single |
| value_bundle_defense | Value Bundle Defense | DEFENSE | multi |
| share_of_voice_defense | Share-of-Voice Defense | DEFENSE | either |

## Requested tactic meanings mapped to actual inventory

These mappings explain existing support. They do not create new tactic IDs. A named topic absent from the catalog is an angle/role within an existing tactic, not a pretend canonical tactic.

| Requested meaning | Existing canonical tactic(s) | Evidence boundary |
|---|---|---|
| Product education; authority | educational_campaign | Product claims from reviewed evidence |
| Product discovery | discovery_campaign | Verified product facts |
| Japan discovery | japan_experience; cultural_campaign | Origin/provenance evidence required; no inferred story |
| New arrival | product_drop; launch_campaign; restock_campaign | Actual novelty/restock evidence required |
| Benefit-led | problem_solution_campaign | Approved product benefit |
| Ingredient/formula breakdown | educational_campaign | Ingredient presence is not finished-product efficacy |
| Buying guide | product_selection | Evidence-based selection criteria; no invented comparison |
| Comparison | competitor_comparison; counter_marketing | Exact counterpart/metric proof required |
| Myth vs fact; customer FAQ | educational_campaign; interactive_campaign | No dedicated myth_vs_fact/FAQ ID; questions/myth wording need review |
| Objection handling | problem_solution_campaign; transparency_campaign | Real objection context, approved answers only |
| Competitor response | competitor_counterattack; price_match_response; value_bundle_defense; share_of_voice_defense | Operational grounding required |
| Cultural/storytelling | cultural_campaign; storytelling_campaign; japan_experience | Verified origin/story |
| Package/product journey | behind_the_scenes; storytelling_campaign | Actual journey evidence, not an invented manufacturing story |
| Promotion | flash_sale; bundle_campaign; personalized_offers | Real authorized offer/stock/terms required |
| Testimonial/social proof | social_proof_campaign; ugc_campaign; ambassador_campaign | Consented attributable evidence, no fabricated quotes |
| Conversion/direct response | paid_ads; abandoned_cart_campaign; upsell_campaign | Strategy distinct from organic; no launch in planning |

## Visual archetypes

| Key | Purpose | Visual logic |
|---|---|---|
| lifestyle_utility | Show how the product fits naturally into real life. | Believable real-life context, clear scale and practical product relevance. |
| feature_demo | Make verified product features easy to understand. | Feature-led framing, close details and explanatory callouts without invented performance. |
| how_it_works | Explain a verified mechanism or use sequence. | Step progression, mechanism views and process-oriented composition. |
| problem_solution | Connect a real customer problem to the product's verified role. | Problem context followed by product relevance and supported benefits without fabricated outcomes. |
| routine_integration | Show where the product belongs in a repeated routine. | Sequence, ritual and contextual continuity. |
| variant_choice | Help the customer choose between real variants. | Orderly comparison while preserving each actual variant's identity. |
| technical_performance | Communicate verified specifications and performance-oriented design. | Precise product details, specification hierarchy and functional context. |
| premium_discovery | Introduce an interesting product as a curated discovery. | Strong product hero, premium editorial context and discovery storytelling. |
| origin_story | Make verified provenance or maker context relevant. | Origin-led atmosphere and authentic context without invented heritage. |
| sensory_experience | Make verified sensory qualities visually tangible. | Close-up material, texture, motion, depth and light. |

## V12.8 bounded adapter support

The product-evidence-only bridge adapts educational_campaign, product_selection, cultural_campaign, japan_experience, storytelling_campaign, problem_solution_campaign, discovery_campaign and paid_ads. Comparison profiles are recognized but fail closed pending counterpart/metric evidence. Other canonical tactics remain in the inventory and existing system; this bridge returns an explicit missing-operational-evidence/adapter error rather than a universal generic campaign. No dedicated new FAQ, myth-vs-fact or ingredient tactic is created.