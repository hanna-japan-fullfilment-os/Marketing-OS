import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useBrand } from '../components/BrandContext'
import { useCalendar } from '../api/hooks'
import { Badge, Button, Card, EmptyState } from '../components/ui'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

export default function CalendarPage() {
  const { brandId } = useBrand()
  const now = new Date()
  const [year, setYear] = useState(now.getUTCFullYear())
  const [month, setMonth] = useState(now.getUTCMonth() + 1)
  const { data: calendar, isLoading } = useCalendar(brandId, year, month)

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }

  function shiftMonth(delta: number) {
    const next = month + delta
    if (next < 1) {
      setYear((y) => y - 1)
      setMonth(12)
    } else if (next > 12) {
      setYear((y) => y + 1)
      setMonth(1)
    } else {
      setMonth(next)
    }
  }

  const totalPublications = calendar?.days.reduce((sum, d) => sum + d.publications.length, 0) ?? 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Calendar</h1>
          <p className="text-sm text-stone-500">
            What actually went out, grouped by day — a real log of publications, not a scheduling tool with
            nothing behind it yet.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => shiftMonth(-1)}>
            <ChevronLeft size={14} />
          </Button>
          <div className="w-40 text-center text-sm font-medium">
            {MONTH_NAMES[month - 1]} {year}
          </div>
          <Button variant="ghost" onClick={() => shiftMonth(1)}>
            <ChevronRight size={14} />
          </Button>
        </div>
      </div>

      {isLoading && <div className="text-sm text-stone-400">Loading…</div>}

      {calendar && totalPublications === 0 && (
        <EmptyState
          title="Nothing published this month"
          description="Log a publication on a campaign's page (once it's Approved or further) and mark it published — it shows up here by date."
        />
      )}

      {calendar && totalPublications > 0 && (
        <div className="space-y-3">
          {calendar.days.map((day) => (
            <Card key={day.date} className="p-4">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-400">
                {new Date(day.date + 'T00:00:00Z').toLocaleDateString(undefined, {
                  weekday: 'long', month: 'long', day: 'numeric', timeZone: 'UTC',
                })}
              </div>
              <div className="space-y-2">
                {day.publications.map((pub) => (
                  <Link
                    key={pub.publication_id}
                    to={`/campaigns/${pub.campaign_id}`}
                    className="flex items-center justify-between rounded-lg border border-stone-100 px-3 py-2 text-sm hover:border-stone-300"
                  >
                    <div>
                      <div className="font-medium text-stone-800">{pub.display_id}</div>
                      <div className="text-xs text-stone-400">{pub.angle || '—'}</div>
                    </div>
                    <Badge tone="muted">{pub.provider.replace('_', ' ')}</Badge>
                  </Link>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
