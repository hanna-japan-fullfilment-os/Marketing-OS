"""Import every model module so Base.metadata knows about all tables
(needed by db.init_db() / Alembic autogenerate).
"""
from . import brand  # noqa: F401
from . import asset  # noqa: F401
from . import campaign  # noqa: F401
from . import research  # noqa: F401
from . import opportunity  # noqa: F401
from . import publishing  # noqa: F401
from . import platform  # noqa: F401
from . import strategy  # noqa: F401
from . import defense  # noqa: F401
from . import product_facts  # noqa: F401
from . import review  # noqa: F401
from . import benchmark  # noqa: F401

from .brand import Brand, BrandAsset, Category, Product
from .asset import Asset
from .campaign import (
    Campaign, CampaignAsset, CampaignSlide, CampaignOutput, CampaignVariant,
    CampaignFingerprint, CampaignSequence, CampaignDiscoveryProduct, CAMPAIGN_STATUSES,
    PlatformCampaignVariant,
)
from .product_facts import VerifiedProductFact
from .research import ResearchRun, ResearchSource, ResearchInsight
from .opportunity import Opportunity, CampaignOpportunity
from .publishing import Publication, PerformanceMetric, PerformanceInsight
from .platform import Job, PromptVersion, AIUsage, AuditEvent, SettingRow, JOB_STATUSES
from .strategy import CampaignStrategyFamily, CampaignStrategyType, STRATEGY_FAMILIES
from .defense import (
    Competitor, CompetitorEvent, DefensePlaybook, COMPETITOR_EVENT_TYPES, COMPETITOR_EVENT_STATUSES,
)
from .review import ReviewFeedback, REVIEW_LEVELS, REVIEW_ACTIONS
from .benchmark import BenchmarkCase, BenchmarkRun, BENCHMARK_CASE_STATUSES, BENCHMARK_TEST_MODES

__all__ = [
    "Brand", "BrandAsset", "Category", "Product",
    "Asset",
    "Campaign", "CampaignAsset", "CampaignSlide", "CampaignOutput", "CampaignVariant",
    "CampaignFingerprint", "CampaignSequence", "CampaignDiscoveryProduct", "CAMPAIGN_STATUSES",
    "PlatformCampaignVariant",
    "ResearchRun", "ResearchSource", "ResearchInsight",
    "Opportunity", "CampaignOpportunity",
    "Publication", "PerformanceMetric", "PerformanceInsight",
    "Job", "PromptVersion", "AIUsage", "AuditEvent", "SettingRow", "JOB_STATUSES",
    "CampaignStrategyFamily", "CampaignStrategyType", "STRATEGY_FAMILIES",
    "Competitor", "CompetitorEvent", "DefensePlaybook",
    "COMPETITOR_EVENT_TYPES", "COMPETITOR_EVENT_STATUSES",
    "VerifiedProductFact",
    "ReviewFeedback", "REVIEW_LEVELS", "REVIEW_ACTIONS",
    "BenchmarkCase", "BenchmarkRun", "BENCHMARK_CASE_STATUSES", "BENCHMARK_TEST_MODES",
]
