import { useState } from 'react'
import { BASE_URL } from '../api/client'
import { useBrand } from '../components/BrandContext'
import { useAssets, useCategories, useScanRepository, useSettings } from '../api/hooks'
import { Button, Card, EmptyState, Badge } from '../components/ui'
import { RefreshCcw } from 'lucide-react'

export default function Library() {
  const { brandId } = useBrand()
  const { data: settings } = useSettings()
  const [categoryId, setCategoryId] = useState<string>('')
  const [unusedOnly, setUnusedOnly] = useState(false)
  const { data: categories } = useCategories(brandId)
  const { data: assets, isLoading } = useAssets(brandId, {
    ...(categoryId ? { category_id: categoryId } : {}),
    ...(unusedOnly ? { unused_only: true } : {}),
  })
  const scan = useScanRepository()

  if (!brandId) {
    return <EmptyState title="No brand selected" description="Select a brand from the sidebar first." />
  }

  const sourceConfigured = !!settings?.source_asset_root

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Asset library</h1>
          <p className="text-sm text-stone-500">
            {sourceConfigured ? settings?.source_asset_root : 'No source repository configured yet.'}
          </p>
        </div>
        <Button
          onClick={() => scan.mutate(brandId)}
          disabled={!sourceConfigured || scan.isPending}
        >
          <RefreshCcw size={14} className={scan.isPending ? 'animate-spin' : ''} />
          {scan.isPending ? 'Scanning…' : 'Scan now'}
        </Button>
      </div>

      {!sourceConfigured && (
        <EmptyState
          title="Set your source folder first"
          description="Go to Settings and set the source repository path (e.g. C:\Marketing\Source) before scanning."
        />
      )}

      {scan.data && (
        <Card className="p-4 text-sm">
          Scanned {scan.data.scanned_files} files — {scan.data.new_assets} new,{' '}
          {scan.data.updated_assets} updated, {scan.data.unchanged_assets} unchanged.
          {scan.data.errors.length > 0 && (
            <div className="mt-2 text-amber-700">{scan.data.errors.length} warning(s) — see server logs.</div>
          )}
        </Card>
      )}

      {sourceConfigured && (
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="">All categories</option>
            {categories?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button
            onClick={() => setUnusedOnly((v) => !v)}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              unusedOnly ? 'border-stone-900 bg-stone-900 text-white' : 'border-stone-300 bg-white text-stone-600'
            }`}
          >
            Unused only
          </button>
        </div>
      )}

      {isLoading && sourceConfigured && <div className="text-sm text-stone-400">Loading…</div>}

      {sourceConfigured && !isLoading && (!assets || assets.length === 0) && (
        <EmptyState
          title="No assets indexed yet"
          description="Click Scan now to index photos from your source folder. Nothing under that folder is ever modified — the scanner only reads it."
        />
      )}

      {assets && assets.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {assets.map((a) => (
            <Card key={a.id} className="overflow-hidden">
              <img
                src={`${BASE_URL}/api/assets/${a.id}/image?max_size=400`}
                alt={a.filename}
                loading="lazy"
                className="aspect-square w-full bg-stone-100 object-cover"
              />
              <div className="space-y-1 p-2.5">
                <div className="truncate text-xs font-medium" title={a.filename}>
                  {a.filename}
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-stone-400">{a.times_used === 0 ? 'unused' : `used ×${a.times_used}`}</span>
                  {a.times_used === 0 ? <Badge tone="success">fresh</Badge> : <Badge tone="muted">used</Badge>}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
