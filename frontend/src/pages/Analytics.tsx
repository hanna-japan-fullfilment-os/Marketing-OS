import { useBrand } from '../components/BrandContext'
import { usePerformanceSummary } from '../api/hooks'
import { Badge, Card, EmptyState, StatCard } from '../components/ui'
import { Link } from 'react-router-dom'

export default function Analytics() {
  const { brandId } = useBrand()
  const { data: summary, isLoading } = usePerformanceSummary(brandId, 90)

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Analytics</h1>
        <p className="text-sm text-stone-500">
          The performance feedback loop: real numbers you (or a future connector) typed in after checking the
          platform's own insights — no estimates, no predicted scores. This is what
          feeds back into which Strategy Library type Autopilot reaches for next.
        </p>
      </div>

      {isLoading && <div className="text-sm text-stone-400">Loading…</div>}

      {summary && summary.totals.publications_with_data === 0 && (
        <EmptyState
          title="No performance data yet"
          description="Log a publication on a campaign's page and add metrics to it — totals and the strategy-type breakdown appear here once at least one exists."
        />
      )}

      {summary && summary.totals.publications_with_data > 0 && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            <StatCard label="Reach (90d)" value={summary.totals.reach.toLocaleString()} />
            <StatCard label="Engagement" value={(summary.totals.likes + summary.totals.comments + summary.totals.shares + summary.totals.saves).toLocaleString()} sub="likes + comments + shares + saves" />
            <StatCard label="Sales" value={summary.totals.sales.toLocaleString()} />
            <StatCard label="Revenue" value={`R$${summary.totals.revenue.toFixed(2)}`} />
          </div>

          <Card className="p-5">
            <h2 className="mb-3 text-sm font-semibold text-stone-800">Performance by strategy type</h2>
            {summary.by_strategy_type.length === 0 ? (
              <p className="text-xs text-stone-400">No campaigns with both a strategy type and recorded metrics yet.</p>
            ) : (
              <div className="space-y-2">
                {summary.by_strategy_type.map((s) => (
                  <div
                    key={s.strategy_type_id}
                    className="flex items-center justify-between rounded-lg border border-stone-100 px-3 py-2 text-sm"
                  >
                    <div>
                      <div className="font-medium text-stone-800">{s.strategy_type_name}</div>
                      <div className="text-xs text-stone-400">
                        {s.campaigns_measured} publication(s) measured
                      </div>
                    </div>
                    <div className="flex items-center gap-4 text-right">
                      <div>
                        <div className="text-xs text-stone-400">Avg. engagement</div>
                        <div className="font-medium">
                          {s.avg_engagement_rate !== null ? `${(s.avg_engagement_rate * 100).toFixed(1)}%` : '—'}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-stone-400">Revenue</div>
                        <div className="font-medium">R${s.total_revenue.toFixed(2)}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="mb-3 text-sm font-semibold text-stone-800">Top campaigns</h2>
            {summary.top_campaigns.length === 0 ? (
              <p className="text-xs text-stone-400">Nothing ranked yet.</p>
            ) : (
              <div className="space-y-2">
                {summary.top_campaigns.map((c) => (
                  <Link
                    key={c.campaign_id}
                    to={`/campaigns/${c.campaign_id}`}
                    className="flex items-center justify-between rounded-lg border border-stone-100 px-3 py-2 text-sm hover:border-stone-300"
                  >
                    <div>
                      <div className="font-medium text-stone-800">{c.display_id}</div>
                      <div className="text-xs text-stone-400">{c.angle || '—'}</div>
                    </div>
                    <div className="flex items-center gap-3">
                      {c.avg_engagement_rate !== null && (
                        <Badge tone="muted">{(c.avg_engagement_rate * 100).toFixed(1)}% engagement</Badge>
                      )}
                      <Badge tone="success">R${c.revenue.toFixed(2)}</Badge>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
