"""Universal campaign archetypes for Marketing OS.

These are communication structures, NOT product categories.

Marketing OS must work across cosmetics, electronics, umbrellas,
wellness devices, household goods, automotive products, food,
fashion, toys, collectibles, kitchenware, stationery and future
categories without forcing them into one visual style.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CampaignArchetypeSpec:
    key: str
    purpose: str
    use_when: str
    visual_logic: str


CAMPAIGN_ARCHETYPES: dict[str, CampaignArchetypeSpec] = {
    "lifestyle_utility": CampaignArchetypeSpec(
        key="lifestyle_utility",
        purpose="Show how the product fits naturally into real life.",
        use_when=(
            "Convenience, portability, everyday usefulness or "
            "lifestyle fit is central to the verified value."
        ),
        visual_logic=(
            "Believable real-life context, clear scale and "
            "practical product relevance."
        ),
    ),

    "feature_demo": CampaignArchetypeSpec(
        key="feature_demo",
        purpose="Make verified product features easy to understand.",
        use_when=(
            "Specific verified functions, materials, controls, "
            "dimensions or construction details matter."
        ),
        visual_logic=(
            "Feature-led framing, close details and explanatory "
            "callouts without invented performance."
        ),
    ),

    "how_it_works": CampaignArchetypeSpec(
        key="how_it_works",
        purpose="Explain a verified mechanism or use sequence.",
        use_when=(
            "Understanding operation or usage materially affects "
            "the buying decision."
        ),
        visual_logic=(
            "Step progression, mechanism views and "
            "process-oriented composition."
        ),
    ),

    "problem_solution": CampaignArchetypeSpec(
        key="problem_solution",
        purpose=(
            "Connect a real customer problem to the product's "
            "verified role."
        ),
        use_when=(
            "Verified facts clearly support a meaningful customer "
            "problem the product addresses."
        ),
        visual_logic=(
            "Problem context followed by product relevance and "
            "supported benefits without fabricated outcomes."
        ),
    ),

    "routine_integration": CampaignArchetypeSpec(
        key="routine_integration",
        purpose="Show where the product belongs in a repeated routine.",
        use_when=(
            "The product naturally belongs in a care, work, travel, "
            "cleaning, cooking or other repeated routine."
        ),
        visual_logic=(
            "Sequence, ritual and contextual continuity."
        ),
    ),

    "variant_choice": CampaignArchetypeSpec(
        key="variant_choice",
        purpose="Help the customer choose between real variants.",
        use_when=(
            "Verified colors, sizes, models, flavors or "
            "configurations meaningfully affect purchase."
        ),
        visual_logic=(
            "Orderly comparison while preserving each actual "
            "variant's identity."
        ),
    ),

    "technical_performance": CampaignArchetypeSpec(
        key="technical_performance",
        purpose=(
            "Communicate verified specifications and "
            "performance-oriented design."
        ),
        use_when=(
            "Verified standards, ratings, materials, technical "
            "features or performance characteristics drive purchase."
        ),
        visual_logic=(
            "Precise product details, specification hierarchy "
            "and functional context."
        ),
    ),

    "premium_discovery": CampaignArchetypeSpec(
        key="premium_discovery",
        purpose=(
            "Introduce an interesting product as a curated discovery."
        ),
        use_when=(
            "Novelty, Japanese origin, distinctiveness or curation "
            "is an important reason customers should notice it."
        ),
        visual_logic=(
            "Strong product hero, premium editorial context and "
            "discovery storytelling."
        ),
    ),

    "origin_story": CampaignArchetypeSpec(
        key="origin_story",
        purpose=(
            "Make verified provenance or maker context relevant."
        ),
        use_when=(
            "Verified maker, region, country, tradition or "
            "provenance materially contributes to appeal."
        ),
        visual_logic=(
            "Origin-led atmosphere and authentic context without "
            "invented heritage."
        ),
    ),

    "sensory_experience": CampaignArchetypeSpec(
        key="sensory_experience",
        purpose=(
            "Make verified sensory qualities visually tangible."
        ),
        use_when=(
            "Texture, finish, material, appearance, fragrance, "
            "taste or another verified sensory quality matters."
        ),
        visual_logic=(
            "Close-up material, texture, motion, depth and light."
        ),
    ),
}


def format_campaign_archetypes_for_prompt() -> str:
    lines = [
        "UNIVERSAL CAMPAIGN ARCHETYPE CATALOG:",
        (
            "Choose exactly ONE primary campaign archetype. "
            "These are communication structures, NOT product categories."
        ),
    ]

    for spec in CAMPAIGN_ARCHETYPES.values():
        lines.append(
            f"- {spec.key}: {spec.purpose} "
            f"USE WHEN: {spec.use_when} "
            f"VISUAL LOGIC: {spec.visual_logic}"
        )

    lines.append(
        "Never choose an archetype merely because a product belongs "
        "to a broad category. Choose from verified facts, campaign "
        "objective, customer buying decision and real visual evidence."
    )

    return "\n".join(lines)
