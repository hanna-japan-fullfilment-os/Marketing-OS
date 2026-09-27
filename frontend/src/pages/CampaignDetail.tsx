import { useState } from 'react'
import type { ComponentType } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { BASE_URL } from '../api/client'
import { useBrand } from '../components/BrandContext'
import {
  useAddMetric,
  useApproveCampaign,
  useAssets,
  useAttachOpportunity,
  useAutoPublishCampaign,
  useCampaign,
  useCampaignOpportunities,
  useCampaignPublications,
  useCreatePublication,
  useCreativeTemplates,
  useDeleteCampaign,
  useGenerateCampaign,
  useGenerateCampaignCopy,
  useGenerateCampaignStrategy,
  useGenerateCampaignVisuals,
  useInvalidateCampaignOnJobDone,
  useJob,
  useMetrics,
  useOpportunities,
  usePlatformCapabilities,
  useProducts,
  useRenderCampaignSlide,
  useSetDiscoveryProducts,
  useSettings,
  useSyncMetricsFromMeta,
  useUpdateCampaign,
  useUpdateCampaignOpportunity,
  useUpdatePublication,
} from '../api/hooks'
import { Badge, Button, Card, EmptyState, Label, Select, Textarea, Input } from '../components/ui'
import {
  ArrowLeft, BarChart3, Check, Compass, ImagePlus, Lightbulb, PenLine, RefreshCw, Send, Sparkles, Trash2, Wand2,
} from 'lucide-react'
import type { VisualsStageOptions } from '../api/hooks'
import type { CampaignOpportunity as CampaignOpportunityType, Job, Publication } from '../api/types'

const STATUS_TONE: Record<string, 'default' | 'success' | 'warning' | 'muted'> = {
  IDEA: 'muted',
  RESEARCHING: 'warning',
  BRIEF_READY: 'warning',
  COPY_READY: 'warning',
  GENERATING: 'warning',
  REVIEW: 'warning',
  APPROVED: 'success',
  PUBLISHED: 'success',
  FAILED: 'muted',
}

const PUBLISHABLE_STATUSES = new Set(['APPROVED', 'EXPORTED', 'SCHEDULED', 'PUBLISHED'])

function _isJobDone(job: Job): boolean {
  return job.status === 'COMPLETED' || job.status === 'FAILED'
}

export default function CampaignDetail() {
  const { campaignId } = useParams<{ campaignId: string }>()
  const navigate = useNavigate()
  const { brandId } = useBrand()
  const { data: campaign, isLoading } = useCampaign(campaignId)
  const deleteCampaign = useDeleteCampaign()
  const updateCampaign = useUpdateCampaign(campaignId)
  const [slideCountInput, setSlideCountInput] = useState('')
  // Round 19: discovery mode's hand-picked product list — only offered on a
  // campaign with no single product_id set (see campaign.structure_mode).
  const { data: discoveryCandidateProducts } = useProducts(brandId, campaign?.category_id ?? undefined)
  const setDiscoveryProducts = useSetDiscoveryProducts(campaignId)
  const [productToAdd, setProductToAdd] = useState('')
  const { data: templatesData } = useCreativeTemplates()
  const { data: platformCapabilities } = usePlatformCapabilities()
  const { data: assets } = useAssets(brandId)
  const renderSlide = useRenderCampaignSlide(campaignId)
  const generateCampaign = useGenerateCampaign(campaignId)
  const generateStrategy = useGenerateCampaignStrategy(campaignId)
  const generateCopy = useGenerateCampaignCopy(campaignId)
  const generateVisuals = useGenerateCampaignVisuals(campaignId)
  // Each /generate* call now queues a background job and returns right away (see
  // JobQueuedResult) — these track which job belongs to which button so its own
  // progress/result can be polled and shown independently of the others.
  const [autopilotJobId, setAutopilotJobId] = useState<string | undefined>(undefined)
  const [strategyJobId, setStrategyJobId] = useState<string | undefined>(undefined)
  const [copyJobId, setCopyJobId] = useState<string | undefined>(undefined)
  const [visualsJobId, setVisualsJobId] = useState<string | undefined>(undefined)
  const { data: autopilotJob } = useJob(autopilotJobId)
  const { data: strategyJob } = useJob(strategyJobId)
  const { data: copyJob } = useJob(copyJobId)
  const { data: visualsJob } = useJob(visualsJobId)
  useInvalidateCampaignOnJobDone(autopilotJob, campaignId)
  useInvalidateCampaignOnJobDone(strategyJob, campaignId)
  useInvalidateCampaignOnJobDone(copyJob, campaignId)
  useInvalidateCampaignOnJobDone(visualsJob, campaignId)
  const approveCampaign = useApproveCampaign(campaignId)
  const { data: opportunities } = useOpportunities(brandId)
  const { data: campaignOpportunities } = useCampaignOpportunities(campaignId)
  const attachOpportunity = useAttachOpportunity(campaignId)
  const updateCampaignOpportunity = useUpdateCampaignOpportunity(campaignId)
  const [selectedOpportunityId, setSelectedOpportunityId] = useState('')

  const { data: publications } = useCampaignPublications(campaignId)
  const createPublication = useCreatePublication(campaignId)
  const updatePublication = useUpdatePublication(campaignId)
  const [pubProvider, setPubProvider] = useState('facebook_page')
  const [pubUrl, setPubUrl] = useState('')

  const { data: settings } = useSettings()
  const autoPublish = useAutoPublishCampaign(campaignId)
  const [autoPublishProvider, setAutoPublishProvider] = useState<'facebook_page' | 'instagram'>('facebook_page')
  const [autoPublishSlide, setAutoPublishSlide] = useState(1)

  const [assetId, setAssetId] = useState('')
  const [templateId, setTemplateId] = useState('feature_showcase')
  const [platformKey, setPlatformKey] = useState('instagram_square')
  const [eyebrow, setEyebrow] = useState('')
  const [headline, setHeadline] = useState('')
  const [body, setBody] = useState('')
  const [cta, setCta] = useState('')
  const [slideNumber, setSlideNumber] = useState(1)
  const [useAiBackground, setUseAiBackground] = useState(false)
  const [useAiBackgroundManual, setUseAiBackgroundManual] = useState(false)
  const [detectProductZone, setDetectProductZone] = useState(false)
  const [detectProductZoneManual, setDetectProductZoneManual] = useState(false)
  // Round 18 made this default to true for Autopilot's main "Run Autopilot"
  // button, matching the backend's default there at the time. Build 1 (Part D)
  // flips that back to false: full AI recreation (still checked against the
  // real product photo via services/orchestrator.py::
  // recreate_creative_image_with_fidelity_gate when used) is now an explicit
  // opt-in everywhere rather than the everyday default — see api/campaigns.py's
  // /generate docstring. Matches "Visuals only" and the manual render form,
  // which already defaulted to false.
  const [recreateWithAi, setRecreateWithAi] = useState(false)
  const [recreateWithAiVisuals, setRecreateWithAiVisuals] = useState(false)
  const [recreateWithAiManual, setRecreateWithAiManual] = useState(false)

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }
  if (isLoading) {
    return <div className="text-sm text-stone-400">Loading…</div>
  }
  if (!campaign) {
    return <EmptyState title="Campaign not found" description="It may have been deleted." />
  }

  const canRender = !!assetId && headline.trim().length > 0 && !renderSlide.isPending
  const autopilotRunning = generateCampaign.isPending || (!!autopilotJob && !_isJobDone(autopilotJob))
  const canRunAutopilot = (campaign.status === 'IDEA' || campaign.status === 'FAILED') && !autopilotRunning

  return (
    <div className="space-y-6">
      <div>
        <Link to="/campaigns" className="inline-flex items-center gap-1 text-xs text-stone-500 hover:text-stone-800">
          <ArrowLeft size={12} /> Back to campaigns
        </Link>
        <div className="mt-2 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">{campaign.display_id}</h1>
            <p className="text-sm text-stone-500">
              {campaign.strategy_type?.name || campaign.angle || campaign.objective}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {campaign.status === 'REVIEW' && (
              <Button
                variant="secondary"
                disabled={approveCampaign.isPending}
                onClick={() => approveCampaign.mutate()}
              >
                <Check size={14} />
                {approveCampaign.isPending ? 'Approving…' : 'Approve'}
              </Button>
            )}
            <Badge tone={STATUS_TONE[campaign.status] ?? 'muted'}>{campaign.status}</Badge>
            <Button
              variant="danger"
              disabled={deleteCampaign.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `Delete campaign ${campaign.display_id}? This permanently removes its rendered images, copy, and any publication/performance history. This can't be undone.`,
                  )
                ) {
                  deleteCampaign.mutate(campaign.id, { onSuccess: () => navigate('/campaigns') })
                }
              }}
            >
              <Trash2 size={14} />
              {deleteCampaign.isPending ? 'Deleting…' : 'Delete'}
            </Button>
          </div>
        </div>
        {approveCampaign.isError && (
          <p className="mt-2 text-xs text-red-700">{(approveCampaign.error as Error).message}</p>
        )}
        {deleteCampaign.isError && (
          <p className="mt-2 text-xs text-red-700">{(deleteCampaign.error as Error).message}</p>
        )}
      </div>

      <Card className="space-y-3 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-800">
              <Sparkles size={14} className="text-amber-600" /> Autopilot
            </h2>
            <p className="mt-1 text-xs text-stone-500">
              Runs the full pipeline end to end: research current trends, generate 2-3 strategy
              candidates, reject anything too close to a past campaign, write the copy, plan the
              carousel, and render every slide — all in one request. Needs an OpenAI API key and
              Output root set in Settings.
            </p>
          </div>
          <Button
            disabled={!canRunAutopilot}
            onClick={() =>
              generateCampaign.mutate(
                { useAiBackground, detectProductZone, recreateWithAi },
                { onSuccess: (data) => setAutopilotJobId(data.job_id) },
              )
            }
            className="shrink-0"
          >
            <Sparkles size={14} />
            {autopilotRunning ? 'Running Autopilot…' : 'Run Autopilot'}
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-600">
          <span>
            Platform/format:{' '}
            {campaign.platform_key ? (
              <strong className="text-stone-800">
                {templatesData?.platform_formats.find((f) => f.key === campaign.platform_key)?.label ??
                  campaign.platform_key}
              </strong>
            ) : (
              <span>account default</span>
            )}
          </span>
          <select
            value={campaign.platform_key ?? ''}
            disabled={updateCampaign.isPending}
            onChange={(e) => updateCampaign.mutate({ platform_key: e.target.value || null })}
            title="Which social platform/format Autopilot and Visuals renders use for every slide in this campaign."
            className="rounded-lg border border-stone-300 bg-white px-2 py-1 text-xs"
          >
            <option value="">Account default</option>
            {templatesData?.platform_formats.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label} ({f.width}×{f.height})
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-wrap items-center gap-4 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-600">
          <div className="flex items-center gap-2">
            <span>Language(s):</span>
            {(platformCapabilities?.languages ?? campaign.languages).map((lang) => {
              const checked = campaign.languages.includes(lang)
              return (
                <label key={lang} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={updateCampaign.isPending}
                    onChange={() => {
                      const next = checked
                        ? campaign.languages.filter((l) => l !== lang)
                        : [...campaign.languages, lang]
                      if (next.length > 0) updateCampaign.mutate({ languages: next })
                    }}
                  />
                  {lang}
                </label>
              )
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span>Target platform(s):</span>
            {(platformCapabilities?.platforms ?? []).map((p) => {
              const checked = campaign.target_platforms.includes(p.key)
              return (
                <label key={p.key} className="flex items-center gap-1" title={p.copy_notes}>
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={updateCampaign.isPending}
                    onChange={() => {
                      const next = checked
                        ? campaign.target_platforms.filter((k) => k !== p.key)
                        : [...campaign.target_platforms, p.key]
                      if (next.length > 0) updateCampaign.mutate({ target_platforms: next })
                    }}
                  />
                  {p.label}
                </label>
              )
            })}
          </div>
        </div>

        {campaign.structure_mode === 'deep_dive' ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-600">
            <span>
              Carousel length:{' '}
              {campaign.target_slide_count ? (
                <strong className="text-stone-800">
                  exactly {campaign.target_slide_count} slide{campaign.target_slide_count === 1 ? '' : 's'}
                </strong>
              ) : (
                <span>model decides (up to 4, whatever the concept needs)</span>
              )}
            </span>
            <Input
              type="number"
              min={1}
              max={20}
              placeholder="e.g. 4"
              value={slideCountInput}
              onChange={(e) => setSlideCountInput(e.target.value)}
              className="w-16 py-1"
            />
            <Button
              variant="secondary"
              disabled={updateCampaign.isPending || !slideCountInput}
              onClick={() => {
                const n = parseInt(slideCountInput, 10)
                if (!Number.isNaN(n)) {
                  updateCampaign.mutate({ target_slide_count: n }, { onSuccess: () => setSlideCountInput('') })
                }
              }}
            >
              Set
            </Button>
            {campaign.target_slide_count != null && (
              <Button
                variant="ghost"
                disabled={updateCampaign.isPending}
                onClick={() => updateCampaign.mutate({ target_slide_count: null })}
              >
                Clear (let the model decide)
              </Button>
            )}
          </div>
        ) : (
          <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-600">
            Carousel length:{' '}
            <strong className="text-stone-800">
              {campaign.discovery_products.length} slide{campaign.discovery_products.length === 1 ? '' : 's'}
            </strong>{' '}
            — one per product picked below (discovery mode; up to 20 products). The "Carousel length" field
            doesn't apply here.
          </div>
        )}
        {updateCampaign.isError && (
          <p className="text-xs text-red-700">{(updateCampaign.error as Error).message}</p>
        )}

        {!campaign.product_id && (
          <div className="space-y-2 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-600">
            <div className="font-medium text-stone-700">
              Discovery products{' '}
              <span className="font-normal text-stone-400">
                — pick several different products to feature one per slide, in this order. Leave empty for the
                original single-photo-pool behavior instead.
              </span>
            </div>
            {campaign.discovery_products.length > 0 && (
              <ol className="space-y-1">
                {campaign.discovery_products.map((dp, i) => (
                  <li key={dp.product_id} className="flex items-center gap-2">
                    <span className="w-5 text-stone-400">{i + 1}.</span>
                    <span className="flex-1 text-stone-700">{dp.name}</span>
                    {i > 0 && (
                      <Button
                        variant="ghost"
                        disabled={setDiscoveryProducts.isPending}
                        onClick={() => {
                          const ids = campaign.discovery_products.map((d) => d.product_id)
                          ;[ids[i - 1], ids[i]] = [ids[i], ids[i - 1]]
                          setDiscoveryProducts.mutate(ids)
                        }}
                      >
                        Move up
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      disabled={setDiscoveryProducts.isPending}
                      onClick={() =>
                        setDiscoveryProducts.mutate(
                          campaign.discovery_products
                            .filter((d) => d.product_id !== dp.product_id)
                            .map((d) => d.product_id),
                        )
                      }
                    >
                      Remove
                    </Button>
                  </li>
                ))}
              </ol>
            )}
            <div className="flex items-center gap-2">
              <select
                value={productToAdd}
                onChange={(e) => setProductToAdd(e.target.value)}
                className="rounded-lg border border-stone-300 bg-white px-2 py-1 text-xs"
              >
                <option value="">Add a product…</option>
                {discoveryCandidateProducts
                  ?.filter((p) => !campaign.discovery_products.some((dp) => dp.product_id === p.id))
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </select>
              <Button
                variant="secondary"
                disabled={
                  !productToAdd || setDiscoveryProducts.isPending || campaign.discovery_products.length >= 20
                }
                onClick={() => {
                  setDiscoveryProducts.mutate(
                    [...campaign.discovery_products.map((d) => d.product_id), productToAdd],
                    { onSuccess: () => setProductToAdd('') },
                  )
                }}
              >
                Add
              </Button>
              {!discoveryCandidateProducts?.length && (
                <span className="text-stone-400">
                  No products found for this category yet — products are auto-detected from a second folder
                  level (Source/&lt;category&gt;/&lt;product&gt;/photo.jpg) when you scan your library.
                </span>
              )}
            </div>
            {setDiscoveryProducts.isError && (
              <p className="text-red-700">{(setDiscoveryProducts.error as Error).message}</p>
            )}
          </div>
        )}
        <label className="flex items-center gap-2 text-xs text-stone-600">
          <input
            type="checkbox"
            checked={recreateWithAi}
            onChange={(e) => setRecreateWithAi(e.target.checked)}
          />
          Recreate each photo with AI (off by default) — sends your real product photo, plus any
          inspiration examples uploaded on the brand's page, to the image model so it reimagines
          the whole scene around your actual product as a dramatic, professionally art-directed
          commercial photograph, and bakes the headline/body/CTA text directly into the graphic.
          Every recreated image is now checked against your real product photo before it's used
          (package shape, logo, label, color, etc.) — if a slide doesn't clearly pass, it's
          regenerated once with a correction, and if it still doesn't pass, that slide falls back
          automatically to the Feature Showcase template with your real, untouched photo instead.
          Turn this off to always use the deterministic Feature Showcase path.
        </label>
        <label className="flex items-center gap-2 text-xs text-stone-600">
          <input
            type="checkbox"
            checked={useAiBackground}
            onChange={(e) => setUseAiBackground(e.target.checked)}
          />
          Use AI-generated background instead (style-guided by this brand's uploaded visual
          references) — only used as a fallback when "Recreate each photo with AI" above is off or
          fails for a slide; needs an OpenAI key.
        </label>
        <label className="flex items-center gap-2 text-xs text-stone-600">
          <input
            type="checkbox"
            checked={detectProductZone}
            onChange={(e) => setDetectProductZone(e.target.checked)}
          />
          Auto-detect product placement per photo (a vision-model call locates the product in
          each photo instead of using the template's fixed layout) — also only relevant as a
          fallback; needs an OpenAI key.
        </label>

        {!canRunAutopilot && !autopilotRunning && (
          <p className="text-xs text-stone-400">
            Autopilot only runs on a campaign in IDEA or FAILED status (currently {campaign.status}).
          </p>
        )}
        {generateCampaign.isError && (
          <p className="text-xs text-red-700">{(generateCampaign.error as Error).message}</p>
        )}
        <JobStatusLine job={autopilotJob} runningLabel="Running Autopilot" doneVerb="Autopilot" campaign={campaign} />
      </Card>

      <Card className="space-y-3 p-5">
        <div>
          <h2 className="text-sm font-semibold text-stone-800">Advanced mode</h2>
          <p className="mt-1 text-xs text-stone-500">
            Run the same pipeline one stage at a time instead of all at once — useful for trying a
            different angle before committing to copy, or re-rendering visuals after adding new
            photos without re-running research. Each stage picks up from the last one's saved
            output, so they can run in separate requests, even days apart.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <StageButton
            icon={Lightbulb}
            label="Strategy only"
            pendingLabel="Researching…"
            mutation={generateStrategy}
            job={strategyJob}
            onJobQueued={setStrategyJobId}
            campaign={campaign}
            disabled={campaign.status !== 'IDEA' && campaign.status !== 'FAILED'}
            disabledHint="Needs IDEA or FAILED status"
          />
          <StageButton
            icon={PenLine}
            label="Copy only"
            pendingLabel="Writing copy…"
            mutation={generateCopy}
            job={copyJob}
            onJobQueued={setCopyJobId}
            campaign={campaign}
          />
          <StageButton
            icon={Wand2}
            label="Visuals only"
            pendingLabel="Rendering…"
            mutation={generateVisuals}
            job={visualsJob}
            onJobQueued={setVisualsJobId}
            campaign={campaign}
            mutateArg={{ useAiBackground, detectProductZone, recreateWithAi: recreateWithAiVisuals }}
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-stone-600">
          <input
            type="checkbox"
            checked={recreateWithAiVisuals}
            onChange={(e) => setRecreateWithAiVisuals(e.target.checked)}
          />
          "Visuals only" above: recreate each photo with AI (bakes the headline/body/CTA text into
          the image itself, styled after inspiration examples, and verified against your real
          product photo before it's used — see Autopilot's checkbox above for details) instead of
          the deterministic background with separately-rendered text (off by default here — needs
          an OpenAI key, unlike the rest of Visuals only)
        </label>
        <p className="text-xs text-stone-400">
          Copy only and Visuals only each need the prior stage to have run for this campaign — if
          not, they'll say so rather than guessing. Visuals only needs no OpenAI key at all unless
          the checkbox above is on.
        </p>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-4 p-5">
          <div>
            <h2 className="text-sm font-semibold text-stone-800">Render a creative</h2>
            <p className="mt-1 text-xs text-stone-500">
              Runs the real creative pipeline — background isolation, compositing your actual product photo,
              and a Playwright-rendered template — right now, no AI call required. Needs Output root set in
              Settings.
            </p>
          </div>

          <div>
            <Label>Product photo</Label>
            <Select value={assetId} onChange={(e) => setAssetId(e.target.value)}>
              <option value="">Select from your asset library…</option>
              {assets?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.filename} ({a.width}×{a.height}
                  {a.times_used > 0 ? `, used ×${a.times_used}` : ''})
                </option>
              ))}
            </Select>
            {assets && assets.length === 0 && (
              <p className="mt-1 text-xs text-amber-700">No assets indexed yet — scan your library first.</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Template</Label>
              <Select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                {templatesData?.templates.map((t) => (
                  <option key={t.id} value={t.id} title={t.description}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Format</Label>
              <Select value={platformKey} onChange={(e) => setPlatformKey(e.target.value)}>
                {templatesData?.platform_formats.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label} ({f.width}×{f.height})
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div>
            <Label>Eyebrow (small label above the headline)</Label>
            <Input value={eyebrow} onChange={(e) => setEyebrow(e.target.value)} placeholder="Direct from Japan" />
          </div>
          <div>
            <Label>Headline</Label>
            <Input value={headline} onChange={(e) => setHeadline(e.target.value)} placeholder="Your new skincare favorite" />
          </div>
          <div>
            <Label>Body copy</Label>
            <Textarea rows={2} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Sourced firsthand, shipped to Brazil." />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>CTA</Label>
              <Input value={cta} onChange={(e) => setCta(e.target.value)} placeholder="Shop the drop" />
            </div>
            <div>
              <Label>Slide number</Label>
              <Input
                type="number"
                min={1}
                value={slideNumber}
                onChange={(e) => setSlideNumber(Math.max(1, Number(e.target.value) || 1))}
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-xs text-stone-600">
            <input
              type="checkbox"
              checked={recreateWithAiManual}
              onChange={(e) => setRecreateWithAiManual(e.target.checked)}
            />
            Recreate this photo with AI (product included, not just the background — and bakes the
            eyebrow/headline/body/CTA text below directly into the image instead of drawing it as
            HTML on top — needs an OpenAI key)
          </label>
          <label className="flex items-center gap-2 text-xs text-stone-600">
            <input
              type="checkbox"
              checked={useAiBackgroundManual}
              onChange={(e) => setUseAiBackgroundManual(e.target.checked)}
            />
            Use AI-generated background instead of the brand-color gradient (only used as a
            fallback when recreation above is off or fails — needs an OpenAI key)
          </label>
          <label className="flex items-center gap-2 text-xs text-stone-600">
            <input
              type="checkbox"
              checked={detectProductZoneManual}
              onChange={(e) => setDetectProductZoneManual(e.target.checked)}
            />
            Auto-detect product placement in this photo instead of the template's fixed layout
            (also only relevant as a fallback — needs an OpenAI key)
          </label>

          <Button
            disabled={!canRender}
            onClick={() =>
              renderSlide.mutate({
                asset_id: assetId,
                slide_number: slideNumber,
                template_id: templateId,
                platform_key: platformKey,
                eyebrow,
                headline,
                body,
                cta,
                use_ai_background: useAiBackgroundManual,
                detect_product_zone: detectProductZoneManual,
                recreate_with_ai: recreateWithAiManual,
              })
            }
          >
            <ImagePlus size={14} />
            {renderSlide.isPending ? 'Rendering…' : 'Render creative'}
          </Button>

          {renderSlide.isError && (
            <p className="text-xs text-red-700">{(renderSlide.error as Error).message}</p>
          )}
        </Card>

        <Card className="space-y-3 p-5">
          <h2 className="text-sm font-semibold text-stone-800">Latest render</h2>
          {renderSlide.data ? (
            <>
              <img
                src={`${BASE_URL}${renderSlide.data.image_url}?t=${Date.now()}`}
                alt="Rendered creative"
                className="w-full rounded-lg border border-stone-200"
              />
              <div className="text-xs text-stone-500">
                {renderSlide.data.width}×{renderSlide.data.height}px ·{' '}
                {renderSlide.data.background_isolator_used === 'ai_recreated'
                  ? 'fully recreated by AI'
                  : `background isolator: ${renderSlide.data.background_isolator_used}`}
                {renderSlide.data.product_zone_detected && ' · product zone auto-detected'}
              </div>
              <QAReport qa={renderSlide.data.qa} />
            </>
          ) : campaign.slides.length > 0 ? (
            <>
              <img
                src={`${BASE_URL}/api/campaigns/${campaign.id}/slides/${campaign.slides[campaign.slides.length - 1].slide_number}/image`}
                alt="Rendered creative"
                className="w-full rounded-lg border border-stone-200"
              />
              <p className="text-xs text-stone-400">Last saved render for this campaign.</p>
            </>
          ) : (
            <EmptyState
              title="Nothing rendered yet"
              description="Fill in the form and click Render creative to produce the first slide."
            />
          )}
        </Card>
      </div>

      {campaign.slides.length > 0 && (
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold text-stone-800">All slides</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            {campaign.slides.map((s) => (
              <div key={s.slide_number} className="space-y-1">
                <img
                  src={`${BASE_URL}/api/campaigns/${campaign.id}/slides/${s.slide_number}/image`}
                  alt={s.headline}
                  className="aspect-square w-full rounded-lg border border-stone-200 object-cover"
                />
                <div className="truncate text-xs text-stone-500" title={s.headline}>
                  #{s.slide_number} — {s.headline}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card className="space-y-4 p-5">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-800">
            <Compass size={14} /> Community drafts
          </h2>
          <p className="mt-1 text-xs text-stone-500">
            Attach a discovered community from the Opportunities page to get a draft post tailored to it. No
            auto-posting — Meta doesn't allow that for Groups an app doesn't administer — you copy the draft and
            post it yourself, then mark it posted here.
          </p>
        </div>

        <div className="flex gap-2">
          <Select value={selectedOpportunityId} onChange={(e) => setSelectedOpportunityId(e.target.value)} className="flex-1">
            <option value="">Select a discovered community…</option>
            {opportunities?.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name} ({o.platform.replace('_', ' ')})
              </option>
            ))}
          </Select>
          <Button
            variant="secondary"
            disabled={!selectedOpportunityId || attachOpportunity.isPending}
            onClick={() =>
              attachOpportunity.mutate(
                { opportunity_id: selectedOpportunityId },
                { onSuccess: () => setSelectedOpportunityId('') },
              )
            }
          >
            Add draft
          </Button>
        </div>
        {opportunities && opportunities.length === 0 && (
          <p className="text-xs text-stone-400">
            No communities discovered yet — visit the Opportunities page to find some for this brand.
          </p>
        )}
        {attachOpportunity.isError && (
          <p className="text-xs text-red-700">{(attachOpportunity.error as Error).message}</p>
        )}

        {campaignOpportunities && campaignOpportunities.length > 0 && (
          <div className="space-y-3 border-t border-stone-100 pt-3">
            {campaignOpportunities.map((co) => (
              <CommunityDraftRow
                key={co.id}
                draft={co}
                onSave={(text) => updateCampaignOpportunity.mutate({ id: co.id, community_post_text: text })}
                onMarkPosted={() => updateCampaignOpportunity.mutate({ id: co.id, posted: true })}
              />
            ))}
          </div>
        )}
      </Card>

      {PUBLISHABLE_STATUSES.has(campaign.status) && (
        <Card className="space-y-4 p-5">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-800">
              <Send size={14} /> Publishing
            </h2>
            <p className="mt-1 text-xs text-stone-500">
              Log where this campaign actually went out — your own Facebook Page/Instagram post, or a manual
              record of a Group post you made by hand. Marking one "published" moves this campaign to
              PUBLISHED and records when.
            </p>
          </div>

          {campaign.slides.length > 0 && (
            <div className="space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-3">
              <div>
                <p className="text-sm font-medium text-stone-800">Auto-publish now</p>
                <p className="mt-0.5 text-xs text-stone-500">
                  Actually posts the rendered slide to your own Facebook Page or linked Instagram Business
                  account via the Graph API — no app, this one included, can auto-post into a Facebook Group.
                  Instagram additionally needs a public URL for the image (see Settings and the README's
                  "Instagram auto-publish" section) since Meta's servers must fetch it themselves.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={autoPublishProvider}
                  onChange={(e) => setAutoPublishProvider(e.target.value as 'facebook_page' | 'instagram')}
                  className="w-48"
                >
                  <option value="facebook_page">Facebook Page</option>
                  <option value="instagram">Instagram</option>
                </Select>
                <Select
                  value={autoPublishSlide}
                  onChange={(e) => setAutoPublishSlide(Number(e.target.value))}
                  className="w-40"
                >
                  {campaign.slides.map((s) => (
                    <option key={s.slide_number} value={s.slide_number}>
                      Slide {s.slide_number}
                    </option>
                  ))}
                </Select>
                <Button
                  disabled={
                    autoPublish.isPending ||
                    (autoPublishProvider === 'facebook_page' ? !settings?.facebook_configured : !settings?.instagram_business_account_id)
                  }
                  onClick={() => autoPublish.mutate({ provider: autoPublishProvider, slide_number: autoPublishSlide })}
                >
                  <Send size={14} /> {autoPublish.isPending ? 'Publishing…' : 'Publish now'}
                </Button>
              </div>
              {autoPublishProvider === 'facebook_page' && !settings?.facebook_configured && (
                <p className="text-xs text-amber-700">
                  Set a Facebook Page access token and Page ID in Settings first.
                </p>
              )}
              {autoPublishProvider === 'instagram' && !settings?.instagram_business_account_id && (
                <p className="text-xs text-amber-700">Set an Instagram Business Account ID in Settings first.</p>
              )}
              {autoPublish.isError && <p className="text-xs text-red-700">{(autoPublish.error as Error).message}</p>}
              {autoPublish.isSuccess && (
                <p className="text-xs text-emerald-700">
                  Published.{' '}
                  {autoPublish.data?.url && (
                    <a href={autoPublish.data.url} target="_blank" rel="noreferrer" className="underline">
                      View post
                    </a>
                  )}
                </p>
              )}
            </div>
          )}

          <div className="flex gap-2 border-t border-stone-100 pt-3">
            <Select value={pubProvider} onChange={(e) => setPubProvider(e.target.value)} className="w-48">
              <option value="facebook_page">Facebook Page</option>
              <option value="instagram">Instagram</option>
              <option value="manual">Manual / Group</option>
            </Select>
            <Input
              value={pubUrl}
              onChange={(e) => setPubUrl(e.target.value)}
              placeholder="Post URL (optional)"
              className="flex-1"
            />
            <Button
              variant="secondary"
              disabled={createPublication.isPending}
              onClick={() =>
                createPublication.mutate(
                  { provider: pubProvider, url: pubUrl, status: 'draft' },
                  { onSuccess: () => setPubUrl('') },
                )
              }
            >
              Log publication
            </Button>
          </div>
          <p className="-mt-2 text-xs text-stone-400">
            Or log a publication you made by hand (a Facebook Group post, or anything posted outside this app).
          </p>
          {createPublication.isError && (
            <p className="text-xs text-red-700">{(createPublication.error as Error).message}</p>
          )}

          {publications && publications.length > 0 ? (
            <div className="space-y-3 border-t border-stone-100 pt-3">
              {publications.map((pub) => (
                <PublicationRow
                  key={pub.id}
                  publication={pub}
                  onMarkPublished={() => updatePublication.mutate({ id: pub.id, status: 'published' })}
                />
              ))}
            </div>
          ) : (
            <p className="text-xs text-stone-400">No publications logged for this campaign yet.</p>
          )}
        </Card>
      )}
    </div>
  )
}

function CommunityDraftRow({
  draft,
  onSave,
  onMarkPosted,
}: {
  draft: CampaignOpportunityType
  onSave: (text: string) => void
  onMarkPosted: () => void
}) {
  const [text, setText] = useState(draft.community_post_text)

  return (
    <div className="space-y-2 rounded-lg border border-stone-200 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-stone-800">{draft.name}</span>
          <Badge tone="muted">{draft.platform.replace('_', ' ')}</Badge>
          {draft.promo_allowed === false && <Badge tone="warning">No direct promo</Badge>}
          {draft.posted && <Badge tone="success">Posted</Badge>}
        </div>
        {!draft.posted && (
          <Button variant="ghost" className="text-xs" onClick={onMarkPosted}>
            <Check size={12} /> Mark posted
          </Button>
        )}
      </div>
      <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} onBlur={() => onSave(text)} />
    </div>
  )
}

interface StageMutationLike {
  isPending: boolean
  isError: boolean
  error: unknown
  mutate: (arg: VisualsStageOptions | undefined, opts: { onSuccess: (data: { job_id: string }) => void }) => void
}

/** Shared progress/result line for a job-backed action (Autopilot or one advanced-
 * mode stage): shows step/progress while the polled job is still running, and a
 * final success/failure line once it reaches a terminal status — see useJob and
 * JobQueuedResult (api/hooks.ts, api/types.ts) for why every /generate* call now
 * needs this instead of just reading a mutation's response body. */
function JobStatusLine({
  job,
  runningLabel,
  doneVerb,
  campaign,
}: {
  job: Job | undefined
  runningLabel: string
  doneVerb: string
  campaign?: { status: string; slides: unknown[] }
}) {
  if (!job) return null
  if (job.status === 'QUEUED' || job.status === 'RUNNING') {
    return (
      <p className="text-xs text-stone-500">
        {runningLabel}… {job.step ? `${job.step} ` : ''}({job.progress}%)
      </p>
    )
  }
  if (job.status === 'FAILED') {
    return <p className="text-xs text-red-700">{doneVerb} failed: {job.error || 'Unknown error.'}</p>
  }
  return (
    <p className="text-xs text-emerald-700">
      {doneVerb} finished
      {campaign ? ` — now ${campaign.status}${campaign.slides.length > 0 ? ` · ${campaign.slides.length} slide(s)` : ''}` : ''}.
    </p>
  )
}

function StageButton({
  icon: Icon,
  label,
  pendingLabel,
  mutation,
  disabled,
  disabledHint,
  mutateArg,
  job,
  onJobQueued,
  campaign,
}: {
  icon: ComponentType<{ size?: number; className?: string }>
  label: string
  pendingLabel: string
  mutation: StageMutationLike
  disabled?: boolean
  disabledHint?: string
  mutateArg?: VisualsStageOptions
  job: Job | undefined
  onJobQueued: (jobId: string) => void
  campaign?: { status: string; slides: unknown[] }
}) {
  const running = mutation.isPending || (!!job && !_isJobDone(job))
  return (
    <div className="space-y-1.5 rounded-lg border border-stone-200 p-3">
      <Button
        variant="secondary"
        className="w-full justify-center"
        disabled={disabled || running}
        onClick={() => mutation.mutate(mutateArg, { onSuccess: (data) => onJobQueued(data.job_id) })}
      >
        <Icon size={14} />
        {running ? pendingLabel : label}
      </Button>
      {disabled && disabledHint && <p className="text-center text-[11px] text-stone-400">{disabledHint}</p>}
      {mutation.isError && <p className="text-[11px] text-red-700">{(mutation.error as Error).message}</p>}
      {job && (
        <div className="text-center text-[11px]">
          <JobStatusLine job={job} runningLabel={pendingLabel} doneVerb={label} campaign={campaign} />
        </div>
      )}
    </div>
  )
}

function PublicationRow({
  publication,
  onMarkPublished,
}: {
  publication: Publication
  onMarkPublished: () => void
}) {
  const [showMetricForm, setShowMetricForm] = useState(false)
  const { data: metrics } = useMetrics(showMetricForm ? publication.id : undefined)
  const addMetric = useAddMetric(publication.id)
  const syncMetrics = useSyncMetricsFromMeta(publication.id)
  const canSyncFromMeta =
    (publication.provider === 'facebook_page' || publication.provider === 'instagram') &&
    !!publication.external_post_id
  const [reach, setReach] = useState('')
  const [likes, setLikes] = useState('')
  const [comments, setComments] = useState('')
  const [shares, setShares] = useState('')
  const [revenue, setRevenue] = useState('')

  return (
    <div className="space-y-2 rounded-lg border border-stone-200 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-stone-800">{publication.provider.replace('_', ' ')}</span>
          <Badge tone={publication.status === 'published' ? 'success' : 'muted'}>{publication.status}</Badge>
          {publication.url && (
            <a
              href={publication.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-stone-500 underline hover:text-stone-800"
            >
              view post
            </a>
          )}
        </div>
        <div className="flex items-center gap-2">
          {publication.status !== 'published' && (
            <Button variant="ghost" className="text-xs" onClick={onMarkPublished}>
              <Check size={12} /> Mark published
            </Button>
          )}
          {canSyncFromMeta && (
            <Button
              variant="ghost"
              className="text-xs"
              disabled={syncMetrics.isPending}
              onClick={() => {
                setShowMetricForm(true)
                syncMetrics.mutate()
              }}
            >
              <RefreshCw size={12} /> {syncMetrics.isPending ? 'Syncing…' : 'Sync from Meta'}
            </Button>
          )}
          <Button variant="ghost" className="text-xs" onClick={() => setShowMetricForm((v) => !v)}>
            <BarChart3 size={12} /> {showMetricForm ? 'Hide metrics' : 'Add metrics'}
          </Button>
        </div>
      </div>

      {showMetricForm && (
        <div className="space-y-2 border-t border-stone-100 pt-2">
          {syncMetrics.isError && (
            <p className="text-xs text-red-700">{(syncMetrics.error as Error).message}</p>
          )}
          {syncMetrics.isSuccess && (
            <p className="text-xs text-emerald-700">Synced the latest numbers from Meta.</p>
          )}
          {metrics && metrics.length > 0 && (
            <ul className="space-y-1 text-xs text-stone-500">
              {metrics.map((m) => (
                <li key={m.id}>
                  {m.source === 'meta_sync' && <Badge tone="default">synced</Badge>}{' '}
                  reach {m.reach} · likes {m.likes} · comments {m.comments} · shares {m.shares} · saves {m.saves}
                  {m.revenue ? ` · R$${m.revenue.toFixed(2)}` : ''}
                </li>
              ))}
            </ul>
          )}
          <div className="grid grid-cols-5 gap-2">
            <Input value={reach} onChange={(e) => setReach(e.target.value)} placeholder="Reach" type="number" />
            <Input value={likes} onChange={(e) => setLikes(e.target.value)} placeholder="Likes" type="number" />
            <Input value={comments} onChange={(e) => setComments(e.target.value)} placeholder="Comments" type="number" />
            <Input value={shares} onChange={(e) => setShares(e.target.value)} placeholder="Shares" type="number" />
            <Input value={revenue} onChange={(e) => setRevenue(e.target.value)} placeholder="Revenue" type="number" />
          </div>
          <Button
            variant="secondary"
            className="text-xs"
            disabled={addMetric.isPending}
            onClick={() =>
              addMetric.mutate(
                {
                  reach: Number(reach) || 0,
                  likes: Number(likes) || 0,
                  comments: Number(comments) || 0,
                  shares: Number(shares) || 0,
                  revenue: Number(revenue) || 0,
                },
                {
                  onSuccess: () => {
                    setReach('')
                    setLikes('')
                    setComments('')
                    setShares('')
                    setRevenue('')
                  },
                },
              )
            }
          >
            Save metrics
          </Button>
        </div>
      )}
    </div>
  )
}

function QAReport({ qa }: { qa: { passed: boolean; issues: string[]; checks: Record<string, boolean> } }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs">
      <div className="flex items-center gap-2">
        <Badge tone={qa.passed ? 'success' : 'warning'}>{qa.passed ? 'QA passed' : 'QA flagged issues'}</Badge>
      </div>
      {qa.issues.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-4 text-amber-800">
          {qa.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
