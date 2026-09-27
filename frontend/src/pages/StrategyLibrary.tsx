import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useBrand } from '../components/BrandContext'
import {
  useCategories,
  useCreateCampaign,
  useCreativeTemplates,
  usePlatformCapabilities,
  useProducts,
  useStrategyLibrary,
} from '../api/hooks'
import { Badge, Button, Card, EmptyState } from '../components/ui'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'
import type { StrategyType } from '../api/types'

const PRODUCT_SCOPE_LABEL: Record<StrategyType['product_scope'], string> = {
  single: 'One product',
  multi: 'Multiple products',
  either: 'One or many',
}

const FAMILY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  ATTACK: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' },
  ACQUIRE: { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200' },
  CONVERT: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
  RETAIN: { bg: 'bg-green-50', text: 'text-green-700', border: 'border-green-200' },
  BRAND: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
  HYPE: { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200' },
  COMMUNITY: { bg: 'bg-pink-50', text: 'text-pink-700', border: 'border-pink-200' },
  DEFENSE: { bg: 'bg-slate-100', text: 'text-slate-700', border: 'border-slate-300' },
}

function StrategyCard({
  type,
  familyKey,
  onStart,
  starting,
}: {
  type: StrategyType
  familyKey: string
  onStart: (key: string) => void
  starting: boolean
}) {
  const [open, setOpen] = useState(false)
  const style = FAMILY_STYLES[familyKey] ?? FAMILY_STYLES.BRAND

  return (
    <Card className={`border ${style.border}`}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div>
          <div className="text-sm font-medium text-stone-900">{type.name}</div>
          <div className="mt-0.5 text-xs text-stone-500">{type.objective}</div>
        </div>
        {open ? <ChevronUp size={16} className="text-stone-400" /> : <ChevronDown size={16} className="text-stone-400" />}
      </button>
      {open && (
        <div className="space-y-3 border-t border-stone-100 px-4 py-3 text-sm">
          <div className="text-xs italic text-stone-500">{type.example}</div>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <div className="font-medium text-stone-600">Trigger</div>
              <div className="text-stone-500">{type.trigger_description || type.trigger_type}</div>
            </div>
            <div>
              <div className="font-medium text-stone-600">Duration</div>
              <div className="text-stone-500">{type.typical_duration}</div>
            </div>
            <div>
              <div className="font-medium text-stone-600">Audience</div>
              <div className="text-stone-500">{type.audience}</div>
            </div>
            <div>
              <div className="font-medium text-stone-600">Budget notes</div>
              <div className="text-stone-500">{type.budget_notes}</div>
            </div>
            <div>
              <div className="font-medium text-stone-600">Products</div>
              <div className="text-stone-500" title="Which carousel structure this strategy naturally fits — informational only, it doesn't restrict what you pick above.">
                {PRODUCT_SCOPE_LABEL[type.product_scope]}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-1">
            {type.psychology.map((p) => (
              <Badge key={p} tone="muted">
                {p.replace(/_/g, ' ')}
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {type.channels.map((c) => (
              <span key={c} className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[11px] text-stone-500">
                {c.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
          <div className="text-xs text-stone-500">
            <span className="font-medium text-stone-600">Success metrics: </span>
            {type.success_metrics.join(', ')}
          </div>
          {type.notes && <div className="text-xs text-stone-400">{type.notes}</div>}
          <Button
            variant="secondary"
            className="mt-1"
            disabled={starting}
            onClick={() => onStart(type.key)}
          >
            <Sparkles size={14} />
            Start campaign with this strategy
          </Button>
        </div>
      )}
    </Card>
  )
}

export default function StrategyLibrary() {
  const { brandId } = useBrand()
  const { data: families, isLoading } = useStrategyLibrary()
  const { data: categories } = useCategories(brandId)
  const [categoryId, setCategoryId] = useState('')
  const { data: products } = useProducts(brandId, categoryId || undefined)
  const [productId, setProductId] = useState('')
  const { data: creativeTemplates } = useCreativeTemplates()
  // Round 20: which platform/format this campaign will render at — sets the new
  // Campaign.platform_key at creation time so every slide comes out the right
  // size from the start. Left blank (the default) falls back to the account-wide
  // AutopilotConfig default, same as every campaign before this feature existed.
  const [platformKey, setPlatformKey] = useState('')
  // Build 1 (Parts B/C): the campaign's real target language(s) and social
  // platform(s) — distinct from platformKey above (that's pixel-rendering
  // format). Defaults match the backend's own defaults (['pt-BR'] /
  // ['instagram']) so a brand that never touches these gets identical behavior
  // to before Build 1 existed.
  const { data: platformCapabilities } = usePlatformCapabilities()
  const [languages, setLanguages] = useState<string[]>(['pt-BR'])
  const [targetPlatforms, setTargetPlatforms] = useState<string[]>(['instagram'])
  const createCampaign = useCreateCampaign()
  const [lastCreated, setLastCreated] = useState<{ id: string; display_id: string } | null>(null)

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }

  const toggleLanguage = (lang: string) => {
    setLanguages((prev) => {
      if (prev.includes(lang)) {
        // Never let the last language be unchecked — a campaign must always
        // target at least one, same rule the backend enforces (400 otherwise).
        return prev.length > 1 ? prev.filter((l) => l !== lang) : prev
      }
      return [...prev, lang]
    })
  }

  const togglePlatform = (key: string) => {
    setTargetPlatforms((prev) => {
      if (prev.includes(key)) {
        return prev.length > 1 ? prev.filter((p) => p !== key) : prev
      }
      return [...prev, key]
    })
  }

  const handleStart = (strategyTypeKey: string) => {
    createCampaign.mutate(
      {
        brand_id: brandId,
        category_id: categoryId || undefined,
        product_id: productId || undefined,
        strategy_type_key: strategyTypeKey,
        platform_key: platformKey || undefined,
        languages,
        target_platforms: targetPlatforms,
      },
      { onSuccess: (res) => setLastCreated({ id: res.id, display_id: res.display_id }) },
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Strategy library</h1>
          <p className="text-sm text-stone-500">
            64 campaign archetypes across 8 strategic families — each with its own psychological objective.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={categoryId}
            onChange={(e) => {
              setCategoryId(e.target.value)
              setProductId('') // a product from the old category no longer applies
            }}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="">No category</option>
            {categories?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
            disabled={!products?.length}
            title={
              productId
                ? 'Deep-dive: this one product, recreated across every slide.'
                : 'Leave unset for a category-wide campaign — hand-pick several products afterward for a ' +
                  'discovery carousel (one slide each), or leave none picked for the original photo-pool behavior.'
            }
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm disabled:bg-stone-50 disabled:text-stone-400"
          >
            <option value="">No specific product</option>
            {products?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={platformKey}
            onChange={(e) => setPlatformKey(e.target.value)}
            title="Which social platform/format to render this campaign's slides at. Leave unset to use your account's default."
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="">Default sizing</option>
            {creativeTemplates?.platform_formats.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="font-medium text-stone-500">Language(s):</span>
          {(platformCapabilities?.languages ?? ['pt-BR', 'en']).map((lang) => (
            <label key={lang} className="flex items-center gap-1 text-stone-700">
              <input type="checkbox" checked={languages.includes(lang)} onChange={() => toggleLanguage(lang)} />
              {lang}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-stone-500">Target platform(s):</span>
          {(platformCapabilities?.platforms ?? []).map((p) => (
            <label key={p.key} className="flex items-center gap-1 text-stone-700" title={p.copy_notes}>
              <input
                type="checkbox"
                checked={targetPlatforms.includes(p.key)}
                onChange={() => togglePlatform(p.key)}
              />
              {p.label}
            </label>
          ))}
        </div>
      </div>

      {lastCreated && (
        <Card className="flex items-center justify-between gap-3 border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          <span>
            Created campaign <strong>{lastCreated.display_id}</strong> in IDEA status. Open it to run Autopilot
            (research, copy, and creative, generated end to end) or work one stage at a time.
          </span>
          <Link to={`/campaigns/${lastCreated.id}`} className="shrink-0">
            <Button variant="secondary" className="whitespace-nowrap">
              Open campaign
            </Button>
          </Link>
        </Card>
      )}

      {isLoading && <div className="text-sm text-stone-400">Loading…</div>}

      {families?.map((family) => {
        const style = FAMILY_STYLES[family.key] ?? FAMILY_STYLES.BRAND
        return (
          <div key={family.id} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${style.bg} ${style.text}`}>
                {family.key}
              </span>
              <h2 className="text-sm font-semibold text-stone-800">{family.name}</h2>
              <span className="text-xs text-stone-400">{family.description}</span>
            </div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {family.types.map((type) => (
                <StrategyCard
                  key={type.id}
                  type={type}
                  familyKey={family.key}
                  onStart={handleStart}
                  starting={createCampaign.isPending}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
