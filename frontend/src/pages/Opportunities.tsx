import { useState } from 'react'
import { useBrand } from '../components/BrandContext'
import {
  useCategories,
  useDiscoverOpportunities,
  useOpportunities,
  useSettings,
  useUpdateOpportunity,
} from '../api/hooks'
import { Badge, Button, Card, EmptyState, Label, Select } from '../components/ui'
import { Compass, ExternalLink, Star, Ban } from 'lucide-react'
import type { Opportunity } from '../api/types'

const JOINED_LABEL: Record<string, string> = {
  not_joined: 'Not joined',
  requested: 'Requested',
  joined: 'Joined',
  rejected: 'Rejected',
}

export default function Opportunities() {
  const { brandId } = useBrand()
  const { data: settings } = useSettings()
  const { data: categories } = useCategories(brandId)
  const { data: opportunities, isLoading } = useOpportunities(brandId)
  const discover = useDiscoverOpportunities()
  const updateOpp = useUpdateOpportunity()

  const [categoryId, setCategoryId] = useState('')

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }

  const openaiConfigured = !!settings?.openai_configured

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Compass size={18} /> Opportunities
        </h1>
        <p className="text-sm text-stone-500">
          Real, verified Facebook Groups, subreddits, and forums where your audience actually gathers — each one
          backed by a source URL the model found via web search, never invented. Meta doesn't let any app
          auto-post into a Group it doesn't administer, so this finds and drafts; you post it yourself.
        </p>
      </div>

      {!openaiConfigured && (
        <EmptyState
          title="Set your OpenAI API key first"
          description="Go to Settings and add your OpenAI API key before discovering communities."
        />
      )}

      {openaiConfigured && (
        <Card className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Category (optional — leave blank for brand-wide)</Label>
              <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                <option value="">All categories</option>
                {categories?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <Button
            disabled={discover.isPending}
            onClick={() => discover.mutate({ brand_id: brandId, category_id: categoryId || undefined })}
          >
            <Compass size={14} />
            {discover.isPending ? 'Searching…' : 'Discover opportunities'}
          </Button>
          {discover.isError && <p className="text-xs text-red-700">{(discover.error as Error).message}</p>}
          {discover.data && (
            <p className="text-xs text-stone-500">
              Found {discover.data.created} new, refreshed {discover.data.updated} existing
              {discover.data.dropped_uncited > 0 &&
                ` — dropped ${discover.data.dropped_uncited} the model couldn't back with a real source`}
              .
            </p>
          )}
        </Card>
      )}

      {isLoading && <div className="text-sm text-stone-400">Loading…</div>}

      {opportunities && opportunities.length === 0 && openaiConfigured && !discover.isPending && (
        <EmptyState
          title="No opportunities yet"
          description="Click Discover opportunities above to find real communities for this brand."
        />
      )}

      {opportunities && opportunities.length > 0 && (
        <div className="space-y-3">
          {opportunities.map((o) => (
            <OpportunityCard
              key={o.id}
              opportunity={o}
              onUpdate={(payload) => updateOpp.mutate({ id: o.id, ...payload })}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function OpportunityCard({
  opportunity,
  onUpdate,
}: {
  opportunity: Opportunity
  onUpdate: (payload: { joined_status?: string; favorite?: boolean; blocked?: boolean }) => void
}) {
  return (
    <Card className="space-y-2 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-stone-800">{opportunity.name}</span>
            <Badge tone="muted">{opportunity.platform.replace('_', ' ')}</Badge>
            {opportunity.promo_allowed === false && <Badge tone="warning">No direct promo</Badge>}
          </div>
          <p className="mt-1 text-xs text-stone-500">{opportunity.description}</p>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-stone-400">
            {opportunity.country && <span>{opportunity.country}</span>}
            {opportunity.audience_size && <span>~{opportunity.audience_size.toLocaleString()} members</span>}
            <span>{Math.round(opportunity.estimated_relevance * 100)}% relevance</span>
          </div>
          {opportunity.posting_rules && (
            <p className="mt-1 text-xs italic text-stone-400">{opportunity.posting_rules}</p>
          )}
          {opportunity.source && (
            <a
              href={opportunity.url || opportunity.source.split(';')[0].trim()}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-xs text-blue-700 hover:underline"
            >
              <ExternalLink size={11} /> Verified source
            </a>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            title={opportunity.favorite ? 'Unfavorite' : 'Favorite'}
            onClick={() => onUpdate({ favorite: !opportunity.favorite })}
            className={`rounded-lg border p-1.5 ${
              opportunity.favorite ? 'border-amber-300 bg-amber-50 text-amber-600' : 'border-stone-200 text-stone-400 hover:bg-stone-50'
            }`}
          >
            <Star size={14} fill={opportunity.favorite ? 'currentColor' : 'none'} />
          </button>
          <button
            title="Block (hide from list)"
            onClick={() => onUpdate({ blocked: true })}
            className="rounded-lg border border-stone-200 p-1.5 text-stone-400 hover:bg-stone-50 hover:text-red-600"
          >
            <Ban size={14} />
          </button>
        </div>
      </div>
      <div>
        <Select
          value={opportunity.joined_status}
          onChange={(e) => onUpdate({ joined_status: e.target.value })}
          className="w-auto text-xs"
        >
          {Object.entries(JOINED_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </div>
    </Card>
  )
}
