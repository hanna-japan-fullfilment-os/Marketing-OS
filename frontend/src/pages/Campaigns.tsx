import { Link } from 'react-router-dom'
import { useBrand } from '../components/BrandContext'
import { useCampaigns, useDeleteCampaign } from '../api/hooks'
import { Badge, Button, Card, EmptyState } from '../components/ui'
import { Trash2 } from 'lucide-react'
import type { CampaignSummary } from '../api/types'

const STATUS_TONE: Record<string, 'default' | 'success' | 'warning' | 'muted'> = {
  IDEA: 'muted',
  REVIEW: 'warning',
  APPROVED: 'success',
  PUBLISHED: 'success',
  FAILED: 'muted',
}

export default function Campaigns() {
  const { brandId } = useBrand()
  const { data: campaigns, isLoading } = useCampaigns(brandId)

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Campaigns</h1>
          <p className="text-sm text-stone-500">Every campaign idea and its lifecycle status.</p>
        </div>
        <Link to="/strategy-library">
          <Button>New campaign from Strategy Library</Button>
        </Link>
      </div>

      {isLoading && <div className="text-sm text-stone-400">Loading…</div>}

      {campaigns && campaigns.length === 0 && (
        <EmptyState
          title="No campaigns yet"
          description="Browse the Strategy Library or log a competitor event in Defense to create your first campaign idea."
        />
      )}

      {campaigns && campaigns.length > 0 && (
        <div className="space-y-2">
          {campaigns.map((c) => (
            <CampaignRow key={c.id} campaign={c} />
          ))}
        </div>
      )}
    </div>
  )
}

/** One row in the campaign list — its own component (rather than an inline
 * `.map()` body) because the delete button needs a per-row useMutation call, and
 * React's rules of hooks don't allow a hook call site inside a callback whose
 * invocation count varies across renders. */
function CampaignRow({ campaign: c }: { campaign: CampaignSummary }) {
  const deleteCampaign = useDeleteCampaign()

  return (
    <Link to={`/campaigns/${c.id}`}>
      <Card className="flex items-center justify-between p-4 transition hover:border-stone-400">
        <div>
          <div className="text-sm font-medium">{c.display_id}</div>
          <div className="text-xs text-stone-400">
            {c.strategy_type_name || c.angle || c.objective}
          </div>
          {deleteCampaign.isError && (
            <div className="mt-1 text-xs text-red-700">{(deleteCampaign.error as Error).message}</div>
          )}
        </div>
        <div className="flex items-center gap-3">
          <Badge tone={STATUS_TONE[c.status] ?? 'muted'}>{c.status}</Badge>
          <Button
            variant="danger"
            className="px-2 py-1.5"
            disabled={deleteCampaign.isPending}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              if (
                window.confirm(
                  `Delete campaign ${c.display_id}? This permanently removes its rendered images, copy, and any publication/performance history. This can't be undone.`,
                )
              ) {
                deleteCampaign.mutate(c.id)
              }
            }}
            title="Delete campaign"
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </Card>
    </Link>
  )
}
