"""Provider abstraction (brief section 2/47/48). Business logic and API routes must
only ever import these Protocols — never the OpenAI SDK (or any future provider's
SDK) directly. This is what lets a second provider, or a publishing connector, be
added later without touching campaign logic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ...schemas.ai import (
    BrandVisualStyleAnalysis, OpportunityDiscoveryResult, ProductFidelityCheck, ProductZoneDetection,
    ResearchQuery, ResearchResult, SourceProductIdentityCheck,
)
from ...schemas.qa import CreativeCritiqueResult

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AIProvider(Protocol):
    """Reasoning / structured generation / vision."""

    async def generate_structured(
        self, *, system: str, user: str, schema: type[SchemaT], model: str
    ) -> SchemaT: ...

    async def vision_describe(self, *, image_path: Path, prompt: str, model: str) -> str: ...

    async def analyze_visual_style(
        self, *, image_paths: list[Path], brand_name: str, model: str
    ) -> BrandVisualStyleAnalysis: ...

    async def detect_product_zone(self, *, image_path: Path, model: str) -> ProductZoneDetection:
        """Looks at one real source photo and locates the product within it — see
        `ProductZoneDetection` for what's returned. Used to fill a template's
        product zone with just the product instead of the whole framed photo,
        per photo rather than one fixed assumption for every upload (see
        `services/orchestrator.py::detect_product_zone`, the best-effort wrapper
        every caller actually uses).
        """
        ...

    async def verify_source_product_identity(
        self, *, source_image_path: Path, product_name: str, category_name: str, model: str
    ) -> SourceProductIdentityCheck:
        """Build 6 repair (Critical Defect 1) — the PRE-GENERATION gate: looks
        at one real source photo and judges whether it actually depicts the
        named catalog product, BEFORE any billed image generation happens.
        See `SourceProductIdentityCheck` for the full contract and why this is
        a distinct question from `check_product_fidelity` (which compares two
        images against each other, after generation, not a photo against a
        catalog name).
        """
        ...

    async def check_product_fidelity(
        self, *, source_image_path: Path, generated_image_path: Path, model: str
    ) -> ProductFidelityCheck:
        """Compares an AI-recreated marketing image against the real source product
        photo it was generated from — the verification gate behind `services/
        orchestrator.py::recreate_creative_image_with_fidelity_gate` (round 18).
        Both images are always the real files on disk; never invented from a
        description. See `ProductFidelityCheck` for exactly what's checked and why
        this is never trusted as a bare boolean.
        """
        ...

    async def critique_creative(
        self, *, image_paths: list[Path], source_image_path: Path | None, context: str, model: str
    ) -> CreativeCritiqueResult:
        """Build 3, Part B: the multimodal structured critic behind `services/
        qa_engine.py::run_creative_qa` — shows the model the real finished
        asset(s) (one or more rendered slide PNGs; more than one only when
        judging carousel consistency across a set) alongside the real source
        product photo (when one is available, for the `product_fidelity`/
        `product_prominence` dimensions), plus `context`: a plain-text bundle
        of everything Part B's input list names (VerifiedProductFacts, brand
        requirements, MasterCampaignConcept, PlatformCampaignVariant fields,
        CampaignCopy, CreativeDirection, locale, platform, carousel context)
        built by the caller — never fabricated inside this method. See
        `CreativeCritiqueResult` for the full scorecard and why every
        dimension is a real judgment, not a placeholder.
        """
        ...


class ResearchProvider(Protocol):
    async def research(self, query: ResearchQuery, *, model: str) -> ResearchResult: ...

    async def discover_opportunities(
        self, query: ResearchQuery, *, model: str
    ) -> OpportunityDiscoveryResult: ...


class ImageProvider(Protocol):
    async def generate(
        self, *, prompt: str, size: str, model: str, reference_images: list[Path] | None = None,
        quality: str = "high",
    ) -> bytes:
        """`quality` (Build 2, Part K — DRAFT/STANDARD/PREMIUM quality modes):
        one of the provider's own accepted quality tiers (`OpenAIProvider`
        passes this straight through to the Images API's own `quality` param —
        "low"/"medium"/"high" for gpt-image-1). Defaults to `"high"`, the same
        value every call site unconditionally used before this parameter
        existed, so an existing caller that never passes it sees byte-for-byte
        the same behavior.
        """
        ...

    async def edit(
        self, *, base_image: Path, prompt: str, model: str, mask: Path | None = None, quality: str = "high",
    ) -> bytes: ...


class PublishTarget(BaseModel):
    provider: str  # facebook_page | instagram
    external_id: str  # the Page ID (facebook_page) or IG Business Account ID (instagram)
    # A publicly-fetchable URL for the image to post. Unused for `facebook_page`
    # (that provider uploads the local file directly). Required for `instagram` —
    # Meta's Content Publishing API only accepts an `image_url` its own servers
    # fetch over the public internet; there is no direct file-upload option for
    # images. See `services/publishing/meta_provider.py` and the README's
    # "Instagram auto-publish" section for how a locally rendered creative gets a
    # public URL (typically a tunnel like ngrok pointed at this backend).
    public_asset_url: str | None = None


class PublishCopy(BaseModel):
    caption: str
    hashtags: list[str] = []


class PublishResult(BaseModel):
    success: bool
    external_post_id: str | None = None
    url: str | None = None
    error: str | None = None


class MetricsFetchResult(BaseModel):
    """Result of reading real engagement numbers back for an already-published
    post (sections 36-38's read-back counterpart to sections 47/48's `publish`).
    `metrics` only ever contains keys the platform actually returned — a metric
    the platform didn't return (or that this app doesn't ask for) is simply
    absent, never filled in as 0, matching the "no fake output" rule this app
    applies to research/opportunities/performance data everywhere else.
    """

    success: bool
    metrics: dict[str, int] = {}
    error: str | None = None


class PublishingProvider(Protocol):
    """Sections 47/48 connectors. `services/publishing/meta_provider.py::
    MetaPublishingProvider` is the first concrete implementation (Facebook Page +
    Instagram, via Meta's Graph API) — manual publication logging (`POST /api/
    campaigns/{id}/publications`) remains the default/fallback flow for anything
    this Protocol doesn't cover (a Facebook Group post, Pinterest, etc. — or simply
    a user who prefers to post by hand). A second connector can register here later
    without campaign logic changes.
    """

    async def publish(
        self, *, target: PublishTarget, assets: list[Path], copy: PublishCopy
    ) -> PublishResult: ...

    async def fetch_metrics(self, *, provider: str, external_post_id: str) -> MetricsFetchResult:
        """Reads back real engagement numbers for a post this connector (or a user
        logging one by hand with a real `external_post_id`) already published.
        Sections 36-38's automated counterpart to typing `PerformanceMetric` rows
        in by hand — see `MetaPublishingProvider.fetch_metrics` for the concrete
        implementation and its stable-fields-first, best-effort-insights design.
        """
        ...
