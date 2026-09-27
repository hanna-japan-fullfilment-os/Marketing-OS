import { useState } from 'react'
import { useBrand } from '../components/BrandContext'
import {
  useCompetitorEvents, useCompetitors, useCreateCampaign, useCreateCompetitor,
  useDefenseRecommendation, useLogCompetitorEvent,
} from '../api/hooks'
import { Badge, Button, Card, EmptyState, Input, Label } from '../components/ui'
import { ShieldAlert } from 'lucide-react'

const EVENT_TYPES = ['price_change', 'promotion_launch', 'new_product', 'campaign_detected', 'restock', 'other']
const SEVERITIES = ['low', 'medium', 'high']

function RecommendationPanel({ eventId, brandId }: { eventId: string; brandId: string }) {
  const { data: recommendations, isLoading } = useDefenseRecommendation(eventId)
  const createCampaign = useCreateCampaign()
  const [created, setCreated] = useState<string | null>(null)

  if (isLoading) return <div className="text-xs text-stone-400">Analyzing…</div>
  if (!recommendations || recommendations.length === 0) {
    return <div className="text-xs text-stone-400">No playbook matched this event yet.</div>
  }

  return (
    <div className="space-y-2">
      {recommendations.map((rec, i) => (
        <div key={rec.playbook_id} className="rounded-lg border border-stone-200 bg-stone-50 p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {i === 0 && <Badge tone="success">Recommended</Badge>}
              <span className="text-sm font-medium">{rec.strategy_type_name}</span>
              <Badge tone="muted">{rec.strategy_family_key}</Badge>
            </div>
            <Button
              variant="secondary"
              onClick={() =>
                createCampaign.mutate(
                  { brand_id: brandId, strategy_type_key: rec.strategy_type_key, triggered_by_event_id: eventId },
                  { onSuccess: (res) => setCreated(res.display_id) },
                )
              }
              disabled={createCampaign.isPending}
            >
              Create campaign
            </Button>
          </div>
          <div className="mt-1 text-xs text-stone-500">{rec.rationale}</div>
        </div>
      ))}
      {created && (
        <div className="text-xs text-emerald-700">
          Created <strong>{created}</strong> — visible in Campaigns as an IDEA.
        </div>
      )}
    </div>
  )
}

export default function Defense() {
  const { brandId } = useBrand()
  const { data: competitors } = useCompetitors(brandId)
  const createCompetitor = useCreateCompetitor()
  const { data: events } = useCompetitorEvents(brandId)
  const logEvent = useLogCompetitorEvent()

  const [newCompetitorName, setNewCompetitorName] = useState('')
  const [selectedCompetitor, setSelectedCompetitor] = useState('')
  const [eventType, setEventType] = useState('promotion_launch')
  const [severity, setSeverity] = useState('medium')
  const [discountPct, setDiscountPct] = useState('')
  const [openEventId, setOpenEventId] = useState<string | null>(null)

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <ShieldAlert size={20} className="text-slate-500" />
          Defense
        </h1>
        <p className="text-sm text-stone-500">
          Log a competitor move and get a specific, explainable recommendation from the Strategy Library — not an
          automatic price match.
        </p>
      </div>

      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">Competitors</h2>
        <div className="flex flex-wrap gap-2">
          {competitors?.map((c) => (
            <span key={c.id} className="rounded-full bg-stone-100 px-3 py-1 text-xs text-stone-600">
              {c.name}
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <Input
            placeholder="Competitor name"
            value={newCompetitorName}
            onChange={(e) => setNewCompetitorName(e.target.value)}
          />
          <Button
            disabled={!newCompetitorName.trim() || createCompetitor.isPending}
            onClick={() => {
              createCompetitor.mutate({ brand_id: brandId, name: newCompetitorName.trim() })
              setNewCompetitorName('')
            }}
          >
            Add
          </Button>
        </div>
      </Card>

      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">Log a competitor event</h2>
        {!competitors || competitors.length === 0 ? (
          <div className="text-xs text-stone-400">Add a competitor above first.</div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <Label>Competitor</Label>
              <select
                value={selectedCompetitor}
                onChange={(e) => setSelectedCompetitor(e.target.value)}
                className="w-full rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm"
              >
                <option value="">Select…</option>
                {competitors.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>Event type</Label>
              <select
                value={eventType}
                onChange={(e) => setEventType(e.target.value)}
                className="w-full rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm"
              >
                {EVENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>Severity</Label>
              <select
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                className="w-full rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm"
              >
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>Discount % (if relevant)</Label>
              <Input
                type="number"
                value={discountPct}
                onChange={(e) => setDiscountPct(e.target.value)}
                placeholder="e.g. 20"
              />
            </div>
          </div>
        )}
        <Button
          disabled={!selectedCompetitor || logEvent.isPending}
          onClick={() =>
            logEvent.mutate({
              competitor_id: selectedCompetitor,
              brand_id: brandId,
              event_type: eventType,
              severity,
              details: discountPct ? { discount_pct: Number(discountPct) } : {},
            })
          }
        >
          Log event
        </Button>
      </Card>

      <div className="space-y-2">
        <h2 className="text-sm font-semibold">Recent events</h2>
        {!events || events.length === 0 ? (
          <EmptyState title="No events logged yet" description="Log a competitor event above to get a recommended response." />
        ) : (
          events.map((event) => (
            <Card key={event.id} className="p-4">
              <button className="flex w-full items-center justify-between text-left" onClick={() => setOpenEventId(openEventId === event.id ? null : event.id)}>
                <div>
                  <div className="text-sm font-medium">{event.event_type.replace(/_/g, ' ')}</div>
                  <div className="text-xs text-stone-400">
                    severity: {event.severity}
                    {typeof event.details.discount_pct === 'number' ? ` · ${event.details.discount_pct}% discount` : ''}
                  </div>
                </div>
                <Badge tone="muted">{event.status}</Badge>
              </button>
              {openEventId === event.id && (
                <div className="mt-3 border-t border-stone-100 pt-3">
                  <RecommendationPanel eventId={event.id} brandId={brandId} />
                </div>
              )}
            </Card>
          ))
        )}
      </div>
    </div>
  )
}
