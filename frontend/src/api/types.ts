export interface Brand {
  id: string
  name: string
  slug: string
  is_active: boolean
  voice: string
  colors: Record<string, unknown>
  typography: Record<string, unknown>
  visual_style: Record<string, unknown>
  forbidden_styles: string[]
  preferred_ctas: string[]
  disallowed_terms: string[]
  disclaimers: string[]
  target_audiences: string[]
  target_countries: string[]
  social_handles: Record<string, unknown>
  website: string
  campaign_rules: Record<string, unknown>
  // Round 20: the brand's own standing creative-direction text (their custom-GPT
  // style prompt, in their own words) — threaded into every AI call (strategy,
  // copy, carousel plan, image generation) alongside the structured brand fields
  // above. Empty string means none set; nothing changes in that case.
  creative_instructions: string
  created_at: string
  updated_at: string
}

export interface BrandAsset {
  id: string
  brand_id: string
  kind: 'logo' | 'font' | 'visual_reference' | 'inspiration'
  category_id: string | null
  label: string
  created_at: string
  updated_at: string
}

export interface BrandVisualStyleAnalysis {
  summary: string
  dominant_colors: string[]
  typography_mood: string
  photography_style: string
  visual_style_descriptors: string[]
  voice_suggestion: string
  forbidden_style_suggestions: string[]
}

export interface Category {
  id: string
  brand_id: string
  name: string
  slug: string
  parent_category_id: string | null
}

export interface Product {
  id: string
  brand_id: string
  category_id: string | null
  name: string
  slug: string
  notes: string
}

export interface Asset {
  id: string
  brand_id: string
  category_id: string | null
  product_id: string | null
  absolute_path: string
  relative_path: string
  filename: string
  extension: string
  sha256: string
  phash: string
  file_size_bytes: number
  width: number
  height: number
  aspect_ratio: number
  image_role: string
  tags: string[]
  is_active: boolean
  times_used: number
  last_used_at: string | null
  visual_description: string
  user_notes: string
}

export interface SettingsData {
  source_asset_root: string
  output_root: string
  openai_configured: boolean
  openai_research_model: string
  openai_campaign_model: string
  openai_vision_model: string
  openai_image_model: string
  trend_research_ttl_hours: number
  category_research_ttl_hours: number
  novelty_too_similar_threshold: number
  novelty_acceptable_threshold: number
  facebook_page_id: string
  facebook_configured: boolean
  instagram_business_account_id: string
  public_base_url: string
  pinterest_board_id: string
  pinterest_configured: boolean
}

export interface DashboardSummary {
  campaigns_this_month: number
  waiting_for_review: number
  published: number
  source_assets_unused: number
  source_assets_total: number
  opportunities_discovered: number
}

export interface ScanResult {
  scanned_files: number
  new_assets: number
  updated_assets: number
  unchanged_assets: number
  skipped_non_images: number
  errors: string[]
}

export interface CampaignSummary {
  id: string
  display_id: string
  status: string
  objective: string
  angle: string
  strategy_type_name?: string | null
  category_id: string | null
  created_at: string
}

export interface StrategyType {
  id: string
  key: string
  name: string
  family_id: string
  secondary_family_keys: string[]
  example: string
  // Round 20: which carousel structure (see CampaignDetail.structure_mode below)
  // this type naturally fits — informational only, shown next to Trigger/
  // Duration/Audience/Budget notes; it never gates or auto-sets a campaign's
  // actual structure.
  product_scope: 'single' | 'multi' | 'either'
  objective: string
  trigger_type: string
  trigger_description: string
  audience: string
  psychology: string[]
  offer_types: string[]
  channels: string[]
  content_types: string[]
  typical_duration: string
  budget_notes: string
  success_metrics: string[]
  notes: string
  is_active: boolean
}

export interface StrategyFamily {
  id: string
  key: string
  name: string
  description: string
  color: string
  sort_order: number
  types: StrategyType[]
}

export interface Competitor {
  id: string
  brand_id: string
  name: string
  website: string
  social_handles: Record<string, unknown>
  notes: string
  monitoring_enabled: boolean
}

export interface CompetitorEvent {
  id: string
  competitor_id: string
  brand_id: string
  event_type: string
  detected_at: string | null
  source: string
  details: Record<string, unknown>
  severity: string
  status: string
  created_at: string
}

export interface DefenseRecommendation {
  playbook_id: string
  strategy_type_key: string
  strategy_type_name: string
  strategy_family_key: string
  rationale: string
  priority: number
}

export interface CampaignSlideSummary {
  slide_number: number
  purpose: string
  headline: string
  body: string
  rendered_asset_path: string
}

export interface DiscoveryProductSummary {
  product_id: string
  name: string
  sort_order: number
}

export interface CampaignDetail {
  id: string
  display_id: string
  status: string
  objective: string
  audience: string
  angle: string
  strategy_type: { key: string; name: string; family_id: string } | null
  hook: string
  main_promise: string
  cta: string
  channels: string[]
  // Legacy single-value field, kept for backward compatibility — `languages`
  // below is the canonical field as of Build 1 (Part B). Not authoritative once
  // `languages` is set.
  language: string
  // Build 1 (Part B): the campaign's real target language(s) — canonical values
  // are 'pt-BR' and 'en' (see PlatformCapabilitiesMeta). May contain both.
  languages: string[]
  // Build 1 (Part C): which real-world social platform(s) this campaign targets
  // (instagram/facebook/tiktok/youtube_shorts/pinterest/linkedin/x) — never
  // assume Instagram. Distinct from `platform_key` below, which is the pixel
  // *rendering* format, not the marketing platform.
  target_platforms: string[]
  geography: string
  notes: string
  target_slide_count: number | null
  // Round 20: which PLATFORM_FORMATS key this campaign renders at. null means
  // "use the account-wide AutopilotConfig default" (instagram_square) — the
  // same fallback every pre-round-20 campaign already had, unchanged.
  platform_key: string | null
  category_id: string | null
  product_id: string | null
  product_name: string | null
  // Round 19: which carousel structure this campaign uses — 'deep_dive' (one
  // product, every slide a different recreation of it) or 'discovery' (one
  // slide per hand-picked product below). Follows entirely from whether a
  // specific product is set / any discovery products have been picked — see
  // api/campaigns.py's get_campaign docstring for the exact rule.
  structure_mode: 'deep_dive' | 'discovery'
  discovery_products: DiscoveryProductSummary[]
  created_at: string
  slides: CampaignSlideSummary[]
}

export interface CreativeTemplateMeta {
  id: string
  name: string
  description: string
}

// Build 1 (Parts B/C): GET /api/campaigns/config/platform-capabilities — the
// real language/platform picker data, distinct from PlatformFormatMeta below
// (that's pixel-format rendering; this is the real-world marketing platform).
export interface PlatformCapabilityMeta {
  key: string
  label: string
  content_types: string[]
  copy_notes: string
}

export interface PlatformCapabilitiesMeta {
  languages: string[]
  platforms: PlatformCapabilityMeta[]
}

// Build 1 (Part A): GET/PUT /api/products/{id}/verified-facts.
export interface VerifiedProductFacts {
  product_id: string
  product_name: string
  category: string | null
  brand_name: string
  owner_notes: string
  verified_description: string
  verified_ingredients: string[]
  verified_features: string[]
  verified_benefits: string[]
  verified_usage: string
  verified_size: string
  verified_variant: string
  verified_price: string
  verified_availability: string
  verified_country_of_origin: string
  verified_claims: string[]
  prohibited_claims: string[]
  source_asset_ids: string[]
  source_references: string[]
  confidence: number
  missing_information: string[]
  provenance: string
}

export type VerifiedProductFactsUpdate = Partial<
  Omit<VerifiedProductFacts, 'product_id' | 'product_name' | 'category' | 'brand_name' | 'owner_notes' | 'missing_information'>
>

export interface PlatformFormatMeta {
  key: string
  label: string
  width: number
  height: number
}

export interface CreativeTemplatesResponse {
  templates: CreativeTemplateMeta[]
  platform_formats: PlatformFormatMeta[]
}

export interface CreativeQAResult {
  passed: boolean
  issues: string[]
  checks: Record<string, boolean>
}

export interface ResearchRunSummary {
  id: string
  category_id: string | null
  ttl_kind: string
  created_at: string
  expires_at: string | null
  insight_count: number
  source_count: number
}

export interface ResearchSourceDetail {
  id: string
  url: string
  title: string
  publisher: string
}

export interface ResearchInsightDetail {
  statement: string
  confidence: number
  freshness: string
  category: string
  recommended_implication: string
  source_ids: string[]
}

export interface ResearchRunDetail extends ResearchRunSummary {
  insights: ResearchInsightDetail[]
  sources: ResearchSourceDetail[]
}

export interface TriggerResearchResult {
  id: string
  was_cached: boolean
  ttl_kind: string
  created_at: string
  expires_at: string | null
  insight_count: number
  source_count: number
}

export interface SlideRenderResult {
  slide_number: number
  rendered_asset_path: string
  image_url: string
  width: number
  height: number
  background_isolator_used: string
  product_zone_detected: boolean
  qa: CreativeQAResult
}

export interface Opportunity {
  id: string
  platform: string
  name: string
  url: string
  description: string
  audience: string
  category_id: string | null
  country: string
  language: string
  estimated_relevance: number
  audience_size: number | null
  promo_allowed: boolean | null
  posting_rules: string
  recommended_content_style: string
  notes: string
  source: string
  status: string
  joined_status: string
  favorite: boolean
  blocked: boolean
  discovered_at: string | null
  last_checked_at: string | null
  last_posted_at: string | null
}

export interface DiscoverOpportunitiesResult {
  created: number
  updated: number
  dropped_uncited: number
  opportunities: Opportunity[]
}

export interface CampaignOpportunity {
  id: string
  opportunity_id: string
  platform: string
  name: string
  url: string
  promo_allowed: boolean | null
  posting_rules: string
  community_post_text: string
  posted: boolean
  posted_at: string | null
}

export interface Publication {
  id: string
  campaign_id: string
  provider: string
  external_post_id: string
  url: string
  status: string
  published_at: string | null
  created_at: string
}

export interface PerformanceMetric {
  id: string
  publication_id: string
  impressions: number
  reach: number
  likes: number
  comments: number
  shares: number
  saves: number
  clicks: number
  leads: number
  bookings: number
  sales: number
  revenue: number
  recorded_at: string | null
  source: string
}

export interface StrategyTypePerformance {
  strategy_type_id: string
  strategy_type_name: string
  campaigns_measured: number
  avg_engagement_rate: number | null
  total_revenue: number
  total_sales: number
}

export interface TopCampaignPerformance {
  campaign_id: string
  display_id: string
  angle: string
  revenue: number
  sales: number
  avg_engagement_rate: number | null
}

export interface PerformanceSummary {
  window_days: number
  totals: {
    impressions: number
    reach: number
    likes: number
    comments: number
    shares: number
    saves: number
    clicks: number
    leads: number
    bookings: number
    sales: number
    revenue: number
    publications_with_data: number
  }
  by_strategy_type: StrategyTypePerformance[]
  top_campaigns: TopCampaignPerformance[]
}

export interface CalendarPublicationEntry {
  publication_id: string
  campaign_id: string
  display_id: string
  angle: string
  provider: string
  url: string
  published_at: string
}

export interface CalendarDay {
  date: string
  publications: CalendarPublicationEntry[]
}

export interface CalendarMonth {
  year: number
  month: number
  days: CalendarDay[]
}

// All four /api/campaigns/{id}/generate* endpoints run their pipeline as a
// background job (see backend api/campaigns.py's module docstring) and return
// immediately with just this — no campaign snapshot, since the run hasn't
// finished yet. Poll it via useJob(job_id) and refetch the campaign once the
// job reaches a terminal status (see useInvalidateCampaignOnJobDone in hooks.ts).
export interface JobQueuedResult {
  job_id: string
  job_status: string
}

export type GenerateCampaignResult = JobQueuedResult
export type StageCampaignResult = JobQueuedResult

export interface Job {
  id: string
  type: string
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  progress: number
  step: string | null
  error: string | null
  attempts?: number
  started_at?: string | null
  completed_at?: string | null
}
