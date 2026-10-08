import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { api } from './client'
import type {
  Asset,
  Brand,
  BrandAsset,
  BrandVisualStyleAnalysis,
  Category,
  CalendarMonth,
  CampaignDetail,
  CampaignOpportunity,
  CampaignSummary,
  Competitor,
  CompetitorEvent,
  CreativeTemplatesResponse,
  DashboardSummary,
  DefenseRecommendation,
  DiscoverOpportunitiesResult,
  DiscoveryProductSummary,
  GenerateCampaignResult,
  Job,
  Opportunity,
  PerformanceMetric,
  PerformanceSummary,
  PlatformCapabilitiesMeta,
  Product,
  Publication,
  ResearchRunDetail,
  ResearchRunSummary,
  ScanResult,
  SettingsData,
  SlideRenderResult,
  StageCampaignResult,
  StrategyFamily,
  TriggerResearchResult,
  VerifiedProductFacts,
  VerifiedProductFactsUpdate,
} from './types'

export function useBrands() {
  return useQuery({ queryKey: ['brands'], queryFn: () => api.get<Brand[]>('/api/brands') })
}

export function useCreateBrand() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { name: string; slug: string }) => api.post<Brand>('/api/brands', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['brands'] }),
  })
}

// Named useBrandDetail (not useBrand) to avoid colliding with
// components/BrandContext.tsx's useBrand(), which returns the globally
// selected { brandId, setBrandId } rather than fetching one brand by id.
export function useBrandDetail(brandId: string | undefined) {
  return useQuery({
    queryKey: ['brand', brandId],
    queryFn: () => api.get<Brand>(`/api/brands/${brandId}`),
    enabled: !!brandId,
  })
}

export function useUpdateBrand(brandId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<Brand>) => api.patch<Brand>(`/api/brands/${brandId}`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['brand', brandId] })
      qc.invalidateQueries({ queryKey: ['brands'] })
    },
  })
}

export function useBrandAssets(brandId: string | undefined, kind?: string, categoryId?: string) {
  const params = new URLSearchParams()
  if (kind) params.set('kind', kind)
  if (categoryId) params.set('category_id', categoryId)
  const qs = params.toString()
  return useQuery({
    queryKey: ['brand-assets', brandId, kind, categoryId],
    queryFn: () => api.get<BrandAsset[]>(`/api/brands/${brandId}/assets${qs ? `?${qs}` : ''}`),
    enabled: !!brandId,
  })
}

export function useUploadBrandAsset(brandId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      file,
      kind,
      label,
      categoryId,
    }: {
      file: File
      kind: string
      label?: string
      categoryId?: string
    }) => {
      const form = new FormData()
      form.set('kind', kind)
      form.set('label', label || '')
      if (categoryId) form.set('category_id', categoryId)
      form.set('file', file)
      return api.postForm<BrandAsset>(`/api/brands/${brandId}/assets`, form)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['brand-assets', brandId] }),
  })
}

export function useDeleteBrandAsset(brandId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (assetId: string) => api.delete<void>(`/api/brands/${brandId}/assets/${assetId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['brand-assets', brandId] }),
  })
}

export function useAnalyzeBrandVisualStyle(brandId: string | undefined) {
  return useMutation({
    mutationFn: () => api.post<BrandVisualStyleAnalysis>(`/api/brands/${brandId}/visual-style/analyze`),
  })
}

export function useCategories(brandId: string | undefined) {
  return useQuery({
    queryKey: ['categories', brandId],
    queryFn: () => api.get<Category[]>(`/api/categories?brand_id=${brandId}`),
    enabled: !!brandId,
  })
}

/** Round 19: products are auto-created by the repository scanner from the
 * second folder level (Source/<category>/<product>/photo.jpg) — no manual
 * product-creation UI exists (or is needed) for the common case. This just
 * lists what the scanner has already found, for picking one on campaign
 * creation (deep-dive) or hand-picking several for a discovery carousel. */
export function useProducts(brandId: string | undefined, categoryId?: string) {
  const params = new URLSearchParams({ brand_id: brandId || '' })
  if (categoryId) params.set('category_id', categoryId)
  return useQuery({
    queryKey: ['products', brandId, categoryId],
    queryFn: () => api.get<Product[]>(`/api/products?${params.toString()}`),
    enabled: !!brandId,
  })
}

export function useAssets(brandId: string | undefined, filters: Record<string, string | boolean> = {}) {
  const params = new URLSearchParams({ brand_id: brandId || '' })
  Object.entries(filters).forEach(([k, v]) => params.set(k, String(v)))
  return useQuery({
    queryKey: ['assets', brandId, filters],
    queryFn: () => api.get<Asset[]>(`/api/assets?${params.toString()}`),
    enabled: !!brandId,
  })
}

export function useDashboard(brandId: string | undefined) {
  return useQuery({
    queryKey: ['dashboard', brandId],
    queryFn: () => api.get<DashboardSummary>(`/api/analytics/dashboard?brand_id=${brandId}`),
    enabled: !!brandId,
  })
}

export function useCampaigns(brandId: string | undefined) {
  return useQuery({
    queryKey: ['campaigns', brandId],
    queryFn: () => api.get<CampaignSummary[]>(`/api/campaigns?brand_id=${brandId}`),
    enabled: !!brandId,
  })
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: () => api.get<SettingsData>('/api/settings') })
}

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<SettingsData> & { openai_api_key?: string; facebook_page_access_token?: string }) =>
      api.patch<SettingsData>('/api/settings', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export function useStrategyLibrary() {
  return useQuery({
    queryKey: ['strategy-library'],
    queryFn: () => api.get<StrategyFamily[]>('/api/strategy-library'),
    staleTime: 5 * 60_000,
  })
}

export function useCreateCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      brand_id: string
      category_id?: string
      // Round 19: leave unset (or omit) for a category-wide campaign — a
      // "discovery" carousel (many different products, one slide each) once
      // products are hand-picked afterward on Campaign Detail, or the original
      // single-photo-pool behavior if none ever are. Set it to scope the
      // campaign to one specific product instead — a "deep-dive" carousel (that
      // one product recreated across every slide). See CampaignDetail's
      // structure_mode for which one a given campaign ends up as.
      product_id?: string
      strategy_type_key?: string
      objective?: string
      triggered_by_event_id?: string
      // Round 20: which PLATFORM_FORMATS key this campaign should render at
      // (see CampaignDetail.platform_key). Omit to leave it unset and fall
      // back to the account-wide AutopilotConfig default.
      platform_key?: string
      // Build 1 (Parts B/C): real target language(s)/platform(s) — see
      // usePlatformCapabilities for the picker data. Omit to get the backend's
      // own default (['pt-BR'] / ['instagram']), same as before these existed.
      languages?: string[]
      target_platforms?: string[]
    }) => api.post<{ id: string; display_id: string; status: string }>('/api/campaigns', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaigns'] }),
  })
}

/** Permanently deletes a campaign (backend: DELETE /api/campaigns/{id}) — cascades
 * to its slides/outputs/publications/community drafts and best-effort removes the
 * real files those pointed at, but never touches the brand's source photos. Takes
 * the campaign id at mutate-time (not hook-creation-time) so one hook instance can
 * serve both the Campaigns list, where each row needs its own id, and Campaign
 * Detail, which always deletes the one campaign it's showing. */
export function useDeleteCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (campaignId: string) => api.delete<void>(`/api/campaigns/${campaignId}`),
    onSuccess: (_data, campaignId) => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

export function useCompetitors(brandId: string | undefined) {
  return useQuery({
    queryKey: ['competitors', brandId],
    queryFn: () => api.get<Competitor[]>(`/api/competitors?brand_id=${brandId}`),
    enabled: !!brandId,
  })
}

export function useCreateCompetitor() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { brand_id: string; name: string; website?: string }) =>
      api.post<Competitor>('/api/competitors', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['competitors'] }),
  })
}

export function useCompetitorEvents(brandId: string | undefined) {
  return useQuery({
    queryKey: ['competitor-events', brandId],
    queryFn: () => api.get<CompetitorEvent[]>(`/api/competitor-events?brand_id=${brandId}`),
    enabled: !!brandId,
  })
}

export function useLogCompetitorEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      competitor_id: string
      brand_id: string
      event_type: string
      severity: string
      details?: Record<string, unknown>
    }) => api.post<CompetitorEvent>('/api/competitor-events', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['competitor-events'] }),
  })
}

export function useDefenseRecommendation(eventId: string | undefined) {
  return useQuery({
    queryKey: ['defense-recommendation', eventId],
    queryFn: () => api.get<DefenseRecommendation[]>(`/api/competitor-events/${eventId}/recommendation`),
    enabled: !!eventId,
  })
}

export function useCampaign(campaignId: string | undefined) {
  return useQuery({
    queryKey: ['campaign', campaignId],
    queryFn: () => api.get<CampaignDetail>(`/api/campaigns/${campaignId}`),
    enabled: !!campaignId,
  })
}

/** Updates the campaign's `target_slide_count` and/or `platform_key` (backend:
 * PATCH /api/campaigns/{id}). `target_slide_count` is how many slides Autopilot's
 * carousel planner should aim for — pass `null` to clear it and go back to the
 * planner's own judgment ("up to" the default cap). `platform_key` is which
 * PLATFORM_FORMATS key this campaign renders at — pass `null` to clear it and fall
 * back to the account-wide AutopilotConfig default; an unknown key is rejected with
 * a 400. Both fields are independently optional — set either one, or both, in a
 * single call. Editable any time, including after Copy/Visuals has already run —
 * changes only affect the next time that stage (or a full Autopilot run) executes. */
export function useUpdateCampaign(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      target_slide_count?: number | null
      platform_key?: string | null
      // Build 1 (Parts B/C): editable post-creation, same "takes effect on the
      // next run, not retroactive" rule as the two fields above. Unlike those,
      // there's no `null`-to-clear case — a campaign must always have at least
      // one language and one target platform, enforced 400 by the backend.
      languages?: string[]
      target_platforms?: string[]
    }) =>
      api.patch<{
        id: string
        target_slide_count: number | null
        platform_key: string | null
        languages: string[]
        target_platforms: string[]
      }>(`/api/campaigns/${campaignId}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaign', campaignId] }),
  })
}

/** Build 1 (Parts B/C): static config for the language/platform pickers on
 * campaign creation and Campaign Detail (backend: GET /api/campaigns/config/
 * platform-capabilities) — not app state, so a long staleTime like
 * useCreativeTemplates above. */
export function usePlatformCapabilities() {
  return useQuery({
    queryKey: ['platform-capabilities'],
    queryFn: () => api.get<PlatformCapabilitiesMeta>('/api/campaigns/config/platform-capabilities'),
    staleTime: 5 * 60_000,
  })
}

/** Build 1 (Part A): a product's Verified Product Facts (backend: GET/PUT
 * /api/products/{id}/verified-facts) — the owner-editable structure that
 * grounds CampaignCopy generation instead of the AI inventing product details. */
export function useVerifiedProductFacts(productId: string | undefined) {
  return useQuery({
    queryKey: ['verified-product-facts', productId],
    queryFn: () => api.get<VerifiedProductFacts>(`/api/products/${productId}/verified-facts`),
    enabled: !!productId,
  })
}

export function useUpdateVerifiedProductFacts(productId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: VerifiedProductFactsUpdate) =>
      api.put<VerifiedProductFacts>(`/api/products/${productId}/verified-facts`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['verified-product-facts', productId] }),
  })
}

/** Round 19: replaces this campaign's hand-picked "discovery" product list
 * wholesale (backend: PUT /api/campaigns/{id}/discovery-products) — list order
 * becomes carousel order. Only meaningful on a campaign with no single
 * `product_id` set (rejected 400 otherwise, see CampaignDetail). Pass an empty
 * array to clear it, falling back to the original single-photo-pool behavior. */
export function useSetDiscoveryProducts(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (productIds: string[]) =>
      api.put<{ id: string; discovery_products: DiscoveryProductSummary[] }>(
        `/api/campaigns/${campaignId}/discovery-products`,
        { product_ids: productIds },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaign', campaignId] }),
  })
}

export function useCreativeTemplates() {
  return useQuery({
    queryKey: ['creative-templates'],
    queryFn: () => api.get<CreativeTemplatesResponse>('/api/campaigns/creative/templates'),
    staleTime: 5 * 60_000,
  })
}

export function useRenderCampaignSlide(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      asset_id: string
      slide_number?: number
      template_id?: string
      platform_key?: string
      eyebrow?: string
      headline: string
      body?: string
      cta?: string
      isolate_background?: boolean
      use_ai_background?: boolean
      detect_product_zone?: boolean
      recreate_with_ai?: boolean
    }) => api.post<SlideRenderResult>(`/api/campaigns/${campaignId}/slides/render`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
      qc.invalidateQueries({ queryKey: ['assets'] })
    },
  })
}

export interface VisualsStageOptions {
  useAiBackground?: boolean
  detectProductZone?: boolean
  // The backend default differs per endpoint as of round 18: `/generate`
  // (main Autopilot) defaults to true (recreation is now checked against the
  // real product photo before use — see api/campaigns.py's docstrings); Visuals
  // stage / manual render still default to false. Sent explicitly whenever the
  // caller sets it (true or false), rather than only when true, so an explicit
  // `false` still overrides whatever the server-side default is.
  recreateWithAi?: boolean
}

function _visualsStageQuery(opts: VisualsStageOptions | undefined): string {
  const params = new URLSearchParams()
  if (opts?.useAiBackground) params.set('use_ai_background', 'true')
  if (opts?.detectProductZone) params.set('detect_product_zone', 'true')
  if (opts?.recreateWithAi !== undefined) params.set('recreate_with_ai', String(opts.recreateWithAi))
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export function useGenerateCampaign(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (opts?: VisualsStageOptions) =>
      api.post<GenerateCampaignResult>(`/api/campaigns/${campaignId}/generate${_visualsStageQuery(opts)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      qc.invalidateQueries({ queryKey: ['assets'] })
      qc.invalidateQueries({ queryKey: ['research-runs'] })
    },
  })
}

function _invalidateAfterStage(qc: ReturnType<typeof useQueryClient>, campaignId: string | undefined) {
  qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
  qc.invalidateQueries({ queryKey: ['campaigns'] })
  qc.invalidateQueries({ queryKey: ['assets'] })
  qc.invalidateQueries({ queryKey: ['research-runs'] })
}

export function useGenerateCampaignStrategy(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    // Strategy has no AI-background/zone-detection concept — the optional
    // parameter exists only so this hook has the same call shape as
    // useGenerateCampaignCopy/useGenerateCampaignVisuals, letting all three share
    // the CampaignDetail StageButton component's single mutation prop type.
    mutationFn: (_opts?: VisualsStageOptions) =>
      api.post<StageCampaignResult>(`/api/campaigns/${campaignId}/generate/strategy`),
    onSuccess: () => _invalidateAfterStage(qc, campaignId),
  })
}

export function useGenerateCampaignCopy(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (_opts?: VisualsStageOptions) =>
      api.post<StageCampaignResult>(`/api/campaigns/${campaignId}/generate/copy`),
    onSuccess: () => _invalidateAfterStage(qc, campaignId),
  })
}

export function useGenerateCampaignVisuals(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (opts?: VisualsStageOptions) =>
      api.post<StageCampaignResult>(`/api/campaigns/${campaignId}/generate/visuals${_visualsStageQuery(opts)}`),
    onSuccess: () => _invalidateAfterStage(qc, campaignId),
  })
}

const _TERMINAL_JOB_STATUSES = new Set(['COMPLETED', 'FAILED'])

/** Polls GET /api/jobs/{id} every 1.5s while the job hasn't finished yet, and stops
 * once it reaches a terminal status — this is what lets the four /generate*
 * endpoints above return immediately (see JobQueuedResult) while the UI still
 * shows live progress and a final result. */
export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.get<Job>(`/api/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && _TERMINAL_JOB_STATUSES.has(status) ? false : 1500
    },
  })
}

/** Once a polled job (see useJob) reaches COMPLETED or FAILED, refetches
 * everything a finished campaign-generation job could have changed — same query
 * keys the old synchronous mutations used to invalidate on their own onSuccess,
 * just triggered once the background job is actually done instead of once the
 * request that queued it returns. Fires only once per (job id, terminal status)
 * pair even though the polled job object keeps being read on every render. */
export function useInvalidateCampaignOnJobDone(job: Job | undefined, campaignId: string | undefined) {
  const qc = useQueryClient()
  const handledRef = useRef<string | null>(null)
  useEffect(() => {
    if (!job || !_TERMINAL_JOB_STATUSES.has(job.status)) return
    const key = `${job.id}:${job.status}`
    if (handledRef.current === key) return
    handledRef.current = key
    qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
    qc.invalidateQueries({ queryKey: ['campaigns'] })
    qc.invalidateQueries({ queryKey: ['assets'] })
    qc.invalidateQueries({ queryKey: ['research-runs'] })
  }, [job?.id, job?.status, campaignId, qc])
}

export function useResearchRuns(brandId: string | undefined) {
  return useQuery({
    queryKey: ['research-runs', brandId],
    queryFn: () => api.get<ResearchRunSummary[]>(`/api/research/runs?brand_id=${brandId}`),
    enabled: !!brandId,
  })
}

export function useResearchRun(runId: string | undefined) {
  return useQuery({
    queryKey: ['research-run', runId],
    queryFn: () => api.get<ResearchRunDetail>(`/api/research/runs/${runId}`),
    enabled: !!runId,
  })
}

export function useTriggerResearch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      brand_id: string
      category_id?: string
      objective?: string
      geography?: string
      audience?: string
      force_refresh?: boolean
    }) => api.post<TriggerResearchResult>('/api/research/run', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['research-runs'] }),
  })
}

export function useOpportunities(brandId: string | undefined, status?: string) {
  const params = new URLSearchParams({ brand_id: brandId || '' })
  if (status) params.set('status', status)
  return useQuery({
    queryKey: ['opportunities', brandId, status],
    queryFn: () => api.get<Opportunity[]>(`/api/opportunities?${params.toString()}`),
    enabled: !!brandId,
  })
}

export function useDiscoverOpportunities() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      brand_id: string
      category_id?: string
      objective?: string
      geography?: string
      audience?: string
    }) => api.post<DiscoverOpportunitiesResult>('/api/opportunities/discover', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['opportunities'] }),
  })
}

export function useUpdateOpportunity() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string
      joined_status?: string
      favorite?: boolean
      blocked?: boolean
      notes?: string
      status?: string
    }) => api.patch<Opportunity>(`/api/opportunities/${id}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['opportunities'] }),
  })
}

export function useCampaignOpportunities(campaignId: string | undefined) {
  return useQuery({
    queryKey: ['campaign-opportunities', campaignId],
    queryFn: () => api.get<CampaignOpportunity[]>(`/api/campaigns/${campaignId}/opportunities`),
    enabled: !!campaignId,
  })
}

export function useAttachOpportunity(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { opportunity_id: string; community_post_text?: string }) =>
      api.post<CampaignOpportunity>(`/api/campaigns/${campaignId}/opportunities`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaign-opportunities', campaignId] }),
  })
}

export function useUpdateCampaignOpportunity(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string
      community_post_text?: string
      posted?: boolean
    }) => api.patch<CampaignOpportunity>(`/api/campaigns/${campaignId}/opportunities/${id}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campaign-opportunities', campaignId] }),
  })
}

export function useApproveCampaign(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<CampaignDetail>(`/api/campaigns/${campaignId}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

export function useCampaignPublications(campaignId: string | undefined) {
  return useQuery({
    queryKey: ['campaign-publications', campaignId],
    queryFn: () => api.get<Publication[]>(`/api/campaigns/${campaignId}/publications`),
    enabled: !!campaignId,
  })
}

export function useCreatePublication(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      provider: string
      external_post_id?: string
      url?: string
      status?: string
      published_at?: string
    }) => api.post<Publication>(`/api/campaigns/${campaignId}/publications`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-publications', campaignId] })
      qc.invalidateQueries({ queryKey: ['publications'] })
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
    },
  })
}

export function useAutoPublishCampaign(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { provider: 'facebook_page' | 'instagram' | 'pinterest'; slide_number?: number }) =>
      api.post<Publication>(`/api/campaigns/${campaignId}/publish`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-publications', campaignId] })
      qc.invalidateQueries({ queryKey: ['publications'] })
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
    },
  })
}

export function usePublications(
  brandId: string | undefined,
  filters: { status?: string; provider?: string } = {},
) {
  const params = new URLSearchParams({ brand_id: brandId || '' })
  if (filters.status) params.set('status', filters.status)
  if (filters.provider) params.set('provider', filters.provider)
  return useQuery({
    queryKey: ['publications', brandId, filters],
    queryFn: () => api.get<Publication[]>(`/api/publications?${params.toString()}`),
    enabled: !!brandId,
  })
}

export function useUpdatePublication(campaignId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string
      status?: string
      url?: string
      external_post_id?: string
      published_at?: string
    }) => api.patch<Publication>(`/api/publications/${id}`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-publications', campaignId] })
      qc.invalidateQueries({ queryKey: ['publications'] })
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
      qc.invalidateQueries({ queryKey: ['performance'] })
      qc.invalidateQueries({ queryKey: ['calendar'] })
    },
  })
}

export function useMetrics(publicationId: string | undefined) {
  return useQuery({
    queryKey: ['metrics', publicationId],
    queryFn: () => api.get<PerformanceMetric[]>(`/api/publications/${publicationId}/metrics`),
    enabled: !!publicationId,
  })
}

export function useAddMetric(publicationId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      impressions?: number
      reach?: number
      likes?: number
      comments?: number
      shares?: number
      saves?: number
      clicks?: number
      leads?: number
      bookings?: number
      sales?: number
      revenue?: number
      recorded_at?: string
    }) => api.post<PerformanceMetric>(`/api/publications/${publicationId}/metrics`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['metrics', publicationId] })
      qc.invalidateQueries({ queryKey: ['performance'] })
    },
  })
}

export function useSyncMetricsFromMeta(publicationId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<PerformanceMetric>(`/api/publications/${publicationId}/metrics/sync`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['metrics', publicationId] })
      qc.invalidateQueries({ queryKey: ['performance'] })
    },
  })
}

export function usePerformanceSummary(brandId: string | undefined, days = 90) {
  return useQuery({
    queryKey: ['performance', brandId, days],
    queryFn: () => api.get<PerformanceSummary>(`/api/analytics/performance?brand_id=${brandId}&days=${days}`),
    enabled: !!brandId,
  })
}

export function useCalendar(brandId: string | undefined, year: number, month: number) {
  return useQuery({
    queryKey: ['calendar', brandId, year, month],
    queryFn: () => api.get<CalendarMonth>(`/api/analytics/calendar?brand_id=${brandId}&year=${year}&month=${month}`),
    enabled: !!brandId,
  })
}

export function useScanRepository() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (brandId: string) => api.post<ScanResult>('/api/repositories/scan', { brand_id: brandId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assets'] })
      qc.invalidateQueries({ queryKey: ['categories'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}
