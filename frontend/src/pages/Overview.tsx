import { Navigate } from 'react-router-dom'
import { useBrand } from '../components/BrandContext'
import { useBrands, useDashboard, useCampaigns } from '../api/hooks'
import { Card, StatCard, EmptyState, Badge } from '../components/ui'

export default function Overview() {
  const { brandId } = useBrand()
  const { data: brands, isLoading: brandsLoading } = useBrands()
  const { data: stats, isLoading } = useDashboard(brandId)
  const { data: campaigns } = useCampaigns(brandId)

  // First run: nothing set up yet. Send new installs through the setup guide
  // instead of a bare "no brand" message — see pages/Onboarding.tsx.
  if (!brandsLoading && brands && brands.length === 0) {
    return <Navigate to="/onboarding" replace />
  }

  if (!brandId) {
    return (
      <EmptyState
        title="No brand selected"
        description="Create or select a brand workspace from the sidebar to see its dashboard."
      />
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Overview</h1>
        <p className="text-sm text-stone-500">A snapshot of this brand's campaigns and library.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Campaigns (30d)" value={isLoading ? '—' : stats?.campaigns_this_month ?? 0} />
        <StatCard label="Waiting for review" value={isLoading ? '—' : stats?.waiting_for_review ?? 0} />
        <StatCard label="Published" value={isLoading ? '—' : stats?.published ?? 0} />
        <StatCard
          label="Assets unused"
          value={isLoading ? '—' : stats?.source_assets_unused ?? 0}
          sub={stats ? `of ${stats.source_assets_total} total` : undefined}
        />
        <StatCard label="Opportunities" value={isLoading ? '—' : stats?.opportunities_discovered ?? 0} />
      </div>

      <Card className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Recent campaigns</h2>
        </div>
        {!campaigns || campaigns.length === 0 ? (
          <EmptyState
            title="No campaigns yet"
            description="Browse the Strategy Library to start one from a campaign archetype, or log a competitor event in Defense to get a recommended response. Scan your photo library first from the Asset Library tab if you haven't already."
          />
        ) : (
          <div className="divide-y divide-stone-100">
            {campaigns.map((c) => (
              <div key={c.id} className="flex items-center justify-between py-2.5 text-sm">
                <div>
                  <div className="font-medium">{c.display_id}</div>
                  <div className="text-xs text-stone-400">{c.angle || c.objective}</div>
                </div>
                <Badge tone="muted">{c.status}</Badge>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
