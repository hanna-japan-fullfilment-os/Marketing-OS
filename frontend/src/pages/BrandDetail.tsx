import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Plus, Sparkles, Trash2, Upload, X } from 'lucide-react'
import { BASE_URL } from '../api/client'
import {
  useAnalyzeBrandVisualStyle,
  useBrandDetail,
  useBrandAssets,
  useCategories,
  useDeleteBrandAsset,
  useUpdateBrand,
  useUploadBrandAsset,
} from '../api/hooks'
import { Badge, Button, Card, EmptyState, Input, Label, Select, Textarea } from '../components/ui'

function assetFileUrl(brandId: string, assetId: string) {
  return `${BASE_URL}/api/brands/${brandId}/assets/${assetId}/file?max_size=320`
}

interface ColorEntry {
  id: string
  key: string
  value: string
}

let _nextColorId = 0
function _newColorId() {
  _nextColorId += 1
  return `color-${_nextColorId}`
}

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/

/** The native <input type="color"> picker only accepts a strict 6-digit #rrggbb
 * value — anything else (empty, 3-digit shorthand, mid-edit text) makes it fall
 * back to a neutral gray swatch instead of erroring, while the adjacent text
 * input still shows exactly what the user typed. */
function toColorPickerValue(hex: string): string {
  return HEX_COLOR_RE.test(hex) ? hex : '#cccccc'
}

export default function BrandDetail() {
  const { brandId } = useParams<{ brandId: string }>()
  const { data: brand, isLoading } = useBrandDetail(brandId)
  const updateBrand = useUpdateBrand(brandId)
  const { data: logos } = useBrandAssets(brandId, 'logo')
  const { data: references } = useBrandAssets(brandId, 'visual_reference')
  const { data: inspirations } = useBrandAssets(brandId, 'inspiration')
  const { data: categories } = useCategories(brandId)
  const uploadAsset = useUploadBrandAsset(brandId)
  const deleteAsset = useDeleteBrandAsset(brandId)
  const analyzeStyle = useAnalyzeBrandVisualStyle(brandId)

  const [inspirationScope, setInspirationScope] = useState('')

  const [voice, setVoice] = useState('')
  const [colorEntries, setColorEntries] = useState<ColorEntry[]>([])
  const [styleTags, setStyleTags] = useState<string[]>([])
  const [forbiddenTags, setForbiddenTags] = useState<string[]>([])
  // Round 20: the brand's own standing creative-direction text (paste in a
  // custom-GPT-style prompt in your own words) — sent alongside every AI call
  // (strategy, copy, carousel plan, image generation), not just image style notes.
  const [creativeInstructions, setCreativeInstructions] = useState('')

  useEffect(() => {
    if (!brand) return
    setVoice(brand.voice || '')
    setColorEntries(
      Object.entries(brand.colors || {}).map(([key, value]) => ({ id: _newColorId(), key, value: String(value) })),
    )
    setStyleTags(Object.values(brand.visual_style || {}).map(String))
    setForbiddenTags(brand.forbidden_styles || [])
    setCreativeInstructions(brand.creative_instructions || '')
  }, [brand?.id])

  if (isLoading) return <div className="text-sm text-stone-500">Loading…</div>
  if (!brand) return <EmptyState title="Brand not found" description="It may have been deleted." />

  const logo = logos && logos.length > 0 ? logos[0] : null

  function updateColorEntry(id: string, patch: Partial<Pick<ColorEntry, 'key' | 'value'>>) {
    setColorEntries((entries) => entries.map((e) => (e.id === id ? { ...e, ...patch } : e)))
  }

  function removeColorEntry(id: string) {
    setColorEntries((entries) => entries.filter((e) => e.id !== id))
  }

  function addColorEntry() {
    setColorEntries((entries) => [...entries, { id: _newColorId(), key: `color_${entries.length + 1}`, value: '#cccccc' }])
  }

  function saveStyle() {
    const colors = Object.fromEntries(
      colorEntries
        .map((e) => [e.key.trim(), e.value.trim()] as const)
        .filter(([key, value]) => key && value),
    )
    const visual_style = Object.fromEntries(styleTags.map((s, i) => [`style_${i + 1}`, s]))
    updateBrand.mutate({ voice, colors, visual_style, forbidden_styles: forbiddenTags, creative_instructions: creativeInstructions })
  }

  function applySuggestions() {
    const result = analyzeStyle.data
    if (!result) return
    setVoice(result.voice_suggestion || voice)
    setColorEntries(
      result.dominant_colors.map((c, i) => ({ id: _newColorId(), key: `color_${i + 1}`, value: c })),
    )
    setStyleTags(
      [result.photography_style, result.typography_mood, ...result.visual_style_descriptors].filter(Boolean),
    )
    if (result.forbidden_style_suggestions.length > 0) {
      setForbiddenTags(Array.from(new Set([...forbiddenTags, ...result.forbidden_style_suggestions])))
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <Link to="/brands" className="inline-flex items-center gap-1 text-sm text-stone-500 hover:text-stone-800">
          <ArrowLeft size={14} /> All brands
        </Link>
        <h1 className="mt-2 text-xl font-semibold">{brand.name}</h1>
        <div className="text-xs text-stone-400">{brand.slug}</div>
      </div>

      <Card className="space-y-3 p-5">
        <div>
          <div className="text-sm font-medium">Logo</div>
          <p className="text-xs text-stone-500">
            Composited onto every rendered creative when one is uploaded — see the QA check for "logo present" on
            Campaign Detail.
          </p>
        </div>
        <div className="flex items-center gap-4">
          {logo ? (
            <div className="relative">
              <img src={assetFileUrl(brand.id, logo.id)} alt="Brand logo" className="h-20 w-20 rounded border border-stone-200 object-contain bg-white" />
              <button
                className="absolute -right-2 -top-2 rounded-full bg-white p-1 text-stone-500 shadow hover:text-red-600"
                onClick={() => deleteAsset.mutate(logo.id)}
                title="Remove logo"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ) : (
            <div className="flex h-20 w-20 items-center justify-center rounded border border-dashed border-stone-300 text-xs text-stone-400">
              No logo
            </div>
          )}
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-stone-300 px-3 py-1.5 text-sm hover:bg-stone-50">
            <Upload size={14} /> {logo ? 'Replace logo' : 'Upload logo'}
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                if (logo) deleteAsset.mutate(logo.id)
                uploadAsset.mutate({ file, kind: 'logo' })
                e.target.value = ''
              }}
            />
          </label>
        </div>
      </Card>

      <Card className="space-y-3 p-5">
        <div>
          <div className="text-sm font-medium">Visual references</div>
          <p className="text-xs text-stone-500">
            Upload a few example photos that capture the look you want — past ads you liked, inspiration shots,
            anything. "Analyze visual style" below reads these and proposes a style guide; when{' '}
            <span className="font-mono">use_ai_background</span> is on for a campaign's Visuals, these same photos
            guide the AI-generated background.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {(references || []).map((r) => (
            <div key={r.id} className="relative">
              <img
                src={assetFileUrl(brand.id, r.id)}
                alt={r.label || 'Visual reference'}
                className="h-24 w-24 rounded border border-stone-200 object-cover"
              />
              <button
                className="absolute -right-2 -top-2 rounded-full bg-white p-1 text-stone-500 shadow hover:text-red-600"
                onClick={() => deleteAsset.mutate(r.id)}
                title="Remove"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <label className="flex h-24 w-24 cursor-pointer flex-col items-center justify-center gap-1 rounded border border-dashed border-stone-300 text-xs text-stone-400 hover:bg-stone-50">
            <Upload size={16} />
            Add photo
            <input
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files || [])
                files.forEach((file) => uploadAsset.mutate({ file, kind: 'visual_reference' }))
                e.target.value = ''
              }}
            />
          </label>
        </div>

        <div className="border-t border-stone-100 pt-3">
          <Button
            variant="secondary"
            disabled={!references || references.length === 0 || analyzeStyle.isPending}
            onClick={() => analyzeStyle.mutate()}
          >
            <Sparkles size={14} className="mr-1.5 inline" />
            {analyzeStyle.isPending ? 'Analyzing…' : 'Analyze visual style with AI'}
          </Button>
          {(!references || references.length === 0) && (
            <p className="mt-1 text-xs text-stone-400">Upload at least one photo above first.</p>
          )}
          {analyzeStyle.isError && (
            <p className="mt-2 text-sm text-red-600">{(analyzeStyle.error as Error).message}</p>
          )}
          {analyzeStyle.isSuccess && analyzeStyle.data && (
            <div className="mt-3 space-y-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
              <p className="text-stone-700">{analyzeStyle.data.summary}</p>
              <div className="flex flex-wrap gap-1.5">
                {analyzeStyle.data.dominant_colors.map((c) => (
                  <span key={c} className="flex items-center gap-1 rounded-full border border-stone-200 bg-white px-2 py-0.5 text-xs">
                    <span className="h-3 w-3 rounded-full border border-stone-300" style={{ backgroundColor: c }} />
                    {c}
                  </span>
                ))}
              </div>
              <p className="text-xs text-stone-500">
                <span className="font-medium text-stone-600">Voice:</span> {analyzeStyle.data.voice_suggestion}
              </p>
              <p className="text-xs text-stone-400">
                This is a proposal only — nothing is saved yet. Use "Apply to form below" and then Save.
              </p>
              <Button onClick={applySuggestions}>Apply to form below</Button>
            </div>
          )}
        </div>
      </Card>

      <Card className="space-y-3 p-5">
        <div>
          <div className="text-sm font-medium">Inspiration examples</div>
          <p className="text-xs text-stone-500">
            Real ads, posts, or carousels you like — from anyone, not just this brand. When
            "Recreate with AI" is on for a campaign (Autopilot, or the checkbox on Visuals only /
            Render a creative), these are handed to the image model alongside your product photo
            as creative-direction reference. Scope one to a category so it's only used for that
            category's campaigns, or leave it brand-wide.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {(inspirations || []).map((r) => (
            <div key={r.id} className="relative">
              <img
                src={assetFileUrl(brand.id, r.id)}
                alt={r.label || 'Inspiration example'}
                className="h-24 w-24 rounded border border-stone-200 object-cover"
              />
              <span className="absolute bottom-0 left-0 right-0 truncate rounded-b bg-black/60 px-1 py-0.5 text-[10px] text-white">
                {r.category_id ? categories?.find((c) => c.id === r.category_id)?.name || 'Category' : 'Brand-wide'}
              </span>
              <button
                className="absolute -right-2 -top-2 rounded-full bg-white p-1 text-stone-500 shadow hover:text-red-600"
                onClick={() => deleteAsset.mutate(r.id)}
                title="Remove"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <label className="flex h-24 w-24 cursor-pointer flex-col items-center justify-center gap-1 rounded border border-dashed border-stone-300 text-xs text-stone-400 hover:bg-stone-50">
            <Upload size={16} />
            Add example
            <input
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files || [])
                files.forEach((file) =>
                  uploadAsset.mutate({ file, kind: 'inspiration', categoryId: inspirationScope || undefined }),
                )
                e.target.value = ''
              }}
            />
          </label>
        </div>
        {categories && categories.length > 0 && (
          <div>
            <Label>Scope the next upload to</Label>
            <Select value={inspirationScope} onChange={(e) => setInspirationScope(e.target.value)}>
              <option value="">Brand-wide (every category)</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </div>
        )}
      </Card>

      <Card className="space-y-3 p-5">
        <div className="text-sm font-medium">Brand voice & style</div>
        <div>
          <Label>Voice</Label>
          <Textarea value={voice} onChange={(e) => setVoice(e.target.value)} rows={2} />
        </div>
        <div>
          <Label>Colors</Label>
          <div className="space-y-2">
            {colorEntries.map((entry) => (
              <div key={entry.id} className="flex items-center gap-2">
                <input
                  type="color"
                  value={toColorPickerValue(entry.value)}
                  onChange={(e) => updateColorEntry(entry.id, { value: e.target.value })}
                  className="h-9 w-9 shrink-0 cursor-pointer rounded border border-stone-300 bg-white p-0.5"
                  title="Pick a color"
                />
                <Input
                  value={entry.key}
                  onChange={(e) => updateColorEntry(entry.id, { key: e.target.value })}
                  placeholder="primary"
                  className="w-32 shrink-0"
                />
                <Input
                  value={entry.value}
                  onChange={(e) => updateColorEntry(entry.id, { value: e.target.value })}
                  placeholder="#f5e6d3"
                  className="flex-1 font-mono"
                />
                <button
                  type="button"
                  className="shrink-0 rounded p-1.5 text-stone-400 hover:bg-stone-100 hover:text-red-600"
                  onClick={() => removeColorEntry(entry.id)}
                  title="Remove color"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <Button variant="secondary" className="text-xs" onClick={addColorEntry}>
              <Plus size={12} /> Add color
            </Button>
          </div>
        </div>
        <div>
          <Label>Visual style descriptors</Label>
          <TagEditor tags={styleTags} onChange={setStyleTags} placeholder="minimal, warm neutrals, editorial…" />
        </div>
        <div>
          <Label>Forbidden styles</Label>
          <TagEditor tags={forbiddenTags} onChange={setForbiddenTags} placeholder="neon colors, stock-photo clichés…" />
        </div>
        <div>
          <Label>Creative instructions (your own standing prompt)</Label>
          <p className="mb-1 text-xs text-stone-500">
            Optional. Paste in your own custom-GPT-style creative direction, in your own words — it's sent
            alongside every AI call for this brand (strategy, copy, carousel planning, and image generation),
            on top of the structured fields above.
          </p>
          <Textarea
            value={creativeInstructions}
            onChange={(e) => setCreativeInstructions(e.target.value)}
            rows={6}
            placeholder="e.g. Always open with a question. Never use the words 'discount' or 'sale'. Product must fill at least 60% of the frame…"
          />
        </div>
        <div className="flex items-center gap-3 pt-1">
          <Button onClick={saveStyle} disabled={updateBrand.isPending}>
            {updateBrand.isPending ? 'Saving…' : 'Save changes'}
          </Button>
          {updateBrand.isSuccess && <Badge tone="success">Saved</Badge>}
        </div>
      </Card>
    </div>
  )
}

/** Chip-based replacement for a plain comma-separated text field: existing values
 * render as removable tags, and a small input + "Add" button (or Enter) appends a
 * new one. Used for visual style descriptors and forbidden styles below. */
function TagEditor({
  tags,
  onChange,
  placeholder,
}: {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder: string
}) {
  const [draft, setDraft] = useState('')

  function addTag() {
    const value = draft.trim()
    if (!value) return
    if (!tags.includes(value)) onChange([...tags, value])
    setDraft('')
  }

  return (
    <div>
      {tags.length > 0 && (
        <div className="mb-1.5 flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="flex items-center gap-1 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-xs text-stone-700"
            >
              {tag}
              <button
                type="button"
                onClick={() => onChange(tags.filter((t) => t !== tag))}
                className="text-stone-400 hover:text-red-600"
                title={`Remove "${tag}"`}
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              addTag()
            }
          }}
          placeholder={placeholder}
        />
        <Button type="button" variant="secondary" className="shrink-0 text-xs" onClick={addTag}>
          <Plus size={12} /> Add
        </Button>
      </div>
    </div>
  )
}
