import { useState } from 'react'
import { useBrand } from '../components/BrandContext'
import {
  useCategories,
  useResearchRun,
  useResearchRuns,
  useSettings,
  useTriggerResearch,
} from '../api/hooks'
import { Badge, Button, Card, EmptyState, Label, Select } from '../components/ui'
import { RefreshCcw, Search } from 'lucide-react'

export default function Research() {
  const { brandId } = useBrand()
  const { data: settings } = useSettings()
  const { data: categories } = useCategories(brandId)
  const { data: runs, isLoading } = useResearchRuns(brandId)
  const trigger = useTriggerResearch()

  const [categoryId, setCategoryId] = useState('')
  const [objective, setObjective] = useState('awareness')
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(undefined)
  const { data: runDetail } = useResearchRun(selectedRunId)

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }

  const openaiConfigured = !!settings?.openai_configured

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Research Radar</h1>
        <p className="text-sm text-stone-500">
          Real, cited research via OpenAI web search — every insight carries a source URL, or it isn't shown.
        </p>
      </div>

      {!openaiConfigured && (
        <EmptyState
          title="Set your OpenAI API key first"
          description="Go to Settings and add your OpenAI API key before running research — nothing here fabricates trend claims without it."
        />
      )}

      {openaiConfigured && (
        <Card className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Category (optional — leave blank for brand-wide research)</Label>
              <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                <option value="">All categories</option>
                {categories?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Objective</Label>
              <Select value={objective} onChange={(e) => setObjective(e.target.value)}>
                {['awareness', 'discovery', 'education', 'engagement', 'lead', 'booking', 'sale', 'retention'].map(
                  (o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ),
                )}
              </Select>
            </div>
          </div>
          <Button
            disabled={trigger.isPending}
            onClick={() =>
              trigger.mutate(
                { brand_id: brandId, category_id: categoryId || undefined, objective },
                { onSuccess: (result) => setSelectedRunId(result.id) },
              )
            }
          >
            <Search size={14} />
            {trigger.isPending ? 'Researching…' : 'Run research'}
          </Button>
          {trigger.isError && <p className="text-xs text-red-700">{(trigger.error as Error).message}</p>}
          {trigger.data && (
            <p className="text-xs text-stone-500">
              {trigger.data.was_cached
                ? 'Returned a cached run — still within its TTL window, no new call was made.'
                : `Ran a fresh research call — ${trigger.data.insight_count} cited insight(s), ${trigger.data.source_count} source(s).`}
            </p>
          )}
        </Card>
      )}

      {isLoading && <div className="text-sm text-stone-400">Loading…</div>}

      {runs && runs.length === 0 && openaiConfigured && (
        <EmptyState title="No research runs yet" description="Run research above to get your first cited insights." />
      )}

      {runs && runs.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            {runs.map((r) => (
              <button key={r.id} onClick={() => setSelectedRunId(r.id)} className="block w-full text-left">
                <Card
                  className={`flex items-center justify-between p-3 transition hover:border-stone-400 ${
                    selectedRunId === r.id ? 'border-stone-900' : ''
                  }`}
                >
                  <div>
                    <div className="text-sm font-medium">{new Date(r.created_at).toLocaleString()}</div>
                    <div className="text-xs text-stone-400">
                      {r.insight_count} insight(s) · {r.source_count} source(s) · {r.ttl_kind}
                    </div>
                  </div>
                  <RefreshCcw size={14} className="text-stone-300" />
                </Card>
              </button>
            ))}
          </div>

          <Card className="space-y-3 p-5">
            {!runDetail ? (
              <p className="text-sm text-stone-400">Select a run to see its cited insights.</p>
            ) : runDetail.insights.length === 0 ? (
              <EmptyState
                title="No citable insights"
                description="The model didn't return anything it could attach a real source to for this query — nothing was fabricated to fill the gap."
              />
            ) : (
              <div className="space-y-4">
                {runDetail.insights.map((insight, i) => (
                  <div key={i} className="space-y-1 border-b border-stone-100 pb-3 last:border-0 last:pb-0">
                    <p className="text-sm text-stone-800">{insight.statement}</p>
                    <p className="text-xs text-stone-500">{insight.recommended_implication}</p>
                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                      <Badge tone="muted">{insight.category}</Badge>
                      <Badge tone="muted">{Math.round(insight.confidence * 100)}% confidence</Badge>
                      {insight.source_ids.map((sid) => {
                        const source = runDetail.sources.find((s) => s.id === sid)
                        return source ? (
                          <a
                            key={sid}
                            href={source.url}
                            target="_blank"
                            rel="noreferrer"
                            className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100"
                          >
                            {source.publisher || new URL(source.url).hostname}
                          </a>
                        ) : null
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
