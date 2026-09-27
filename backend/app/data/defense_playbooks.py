"""Default (brand_id=None, i.e. global) Defense playbooks — the rule set the
Defense engine matches a CompetitorEvent against to recommend a Strategy Library
response. `condition` keys are checked against the triggering event's `details`
dict using simple >=/<= comparisons (see app/services/defense.py). Rows are
evaluated in `priority` order (lowest first); the first match wins per event_type.

These are sensible defaults any brand can start from; a brand can add its own rows
(with its brand_id set) that take priority over the global ones.
"""

DEFAULT_PLAYBOOKS = [
    # promotion_launch: prefer a value bundle over a raw price match, but escalate
    # to a full counterattack for large discounts, and fall back to a price match
    # only when nothing else is configured.
    dict(event_type="promotion_launch", min_severity="high", condition={"discount_pct_gte": 20},
         recommended_strategy_key="competitor_counterattack", priority=10,
         rationale="A 20%+ competitor discount is a serious share-of-wallet threat — respond with a full targeted campaign, not just a price move."),
    dict(event_type="promotion_launch", min_severity="medium", condition={"discount_pct_gte": 10},
         recommended_strategy_key="value_bundle_defense", priority=20,
         rationale="A moderate discount is usually better countered with perceived extra value than by cutting your own margin."),
    dict(event_type="promotion_launch", min_severity="low", condition={},
         recommended_strategy_key="counter_marketing", priority=90,
         rationale="A minor promotion mainly calls for reasserting your value proposition, not a reactive discount."),

    dict(event_type="price_change", min_severity="high", condition={"discount_pct_gte": 15},
         recommended_strategy_key="value_bundle_defense", priority=10,
         rationale="Large price cuts are usually better met with a value bundle to protect margin."),
    dict(event_type="price_change", min_severity="medium", condition={}, recommended_strategy_key="price_match_response",
         priority=50, rationale="A moderate, directly comparable price cut may warrant a direct match if margin allows."),

    dict(event_type="new_product", min_severity="medium", condition={},
         recommended_strategy_key="competitor_comparison", priority=30,
         rationale="A new competitor SKU is a good moment for a factual value comparison."),
    dict(event_type="new_product", min_severity="high", condition={},
         recommended_strategy_key="competitor_counterattack", priority=20,
         rationale="A significant new competitor launch warrants a full counter-campaign, not just a comparison post."),

    dict(event_type="campaign_detected", min_severity="high", condition={},
         recommended_strategy_key="share_of_voice_defense", priority=20,
         rationale="A high-visibility competitor campaign calls for reasserting your own authority/story, not copying them."),
    dict(event_type="campaign_detected", min_severity="medium", condition={},
         recommended_strategy_key="share_of_voice_defense", priority=40,
         rationale="Even moderate competitor buzz is worth a timely owned-content response."),

    dict(event_type="restock", min_severity="low", condition={},
         recommended_strategy_key="counter_marketing", priority=80,
         rationale="A competitor restock rarely needs more than reasserting your own availability/value."),

    dict(event_type="other", min_severity="low", condition={}, recommended_strategy_key="counter_marketing",
         priority=100, rationale="Default fallback for uncategorized competitor activity."),
]
