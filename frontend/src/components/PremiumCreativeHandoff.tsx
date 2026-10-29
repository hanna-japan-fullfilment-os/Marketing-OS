import { useEffect, useState } from 'react'
import { BASE_URL } from '../api/client'

type Brief = { key: string; slide_number: number; slide_role: string; locale: string; channel: string; approved_copy: { key: string; text: string }[] }
type Slide = { slide_key: string; filename: string; sha256: string; approval_status: string; qa_status: string; creation_source: string }
type View = { enabled: boolean; blocked?: string; briefs?: Brief[]; readiness?: { version: number; status: string; EXPECTED_SLIDE_COUNT: number; IMPORTED_SLIDE_COUNT: number; APPROVED_SLIDE_COUNT: number; REJECTED_SLIDE_COUNT: number; canonical_handoff_current: boolean; slides: Slide[] } }
const reasons = ['product_fidelity', 'copy', 'typography', 'hierarchy', 'brand_mismatch', 'composition', 'cta', 'visual_quality', 'other']

export default function PremiumCreativeHandoff({ campaignId }: { campaignId: string }) {
  const base = `${BASE_URL}/api/campaigns/${encodeURIComponent(campaignId)}/premium-creative`
  const [view, setView] = useState<View | null>(null)
  const [key, setKey] = useState('')
  const [image, setImage] = useState<File | null>(null)
  const [reviewer, setReviewer] = useState('')
  const [productVisible, setProductVisible] = useState(false)
  const [productFaithful, setProductFaithful] = useState(false)
  const [observed, setObserved] = useState('')
  const [reason, setReason] = useState(reasons[0])
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function checked(url: string, init?: RequestInit) {
    const response = await fetch(url, init)
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status})`)
    }
    return response
  }
  async function refresh() {
    const current = await (await checked(base)).json() as View
    setView(current)
    setKey(previous => current.briefs?.some(b => b.key === previous) ? previous : current.briefs?.[0]?.key ?? '')
  }
  useEffect(() => {
    let cancelled = false
    fetch(base).then(async r => { if (!r.ok) throw new Error('Could not load premium creative workflow'); return r.json() as Promise<View> })
      .then(v => { if (!cancelled) { setView(v); setKey(v.briefs?.[0]?.key ?? '') } })
      .catch(e => { if (!cancelled) setError(String(e)) })
    return () => { cancelled = true }
  }, [base])
  async function act(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action(); await refresh() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function download(url: string, name: string) {
    const response = await checked(url, { method: 'POST' })
    const href = URL.createObjectURL(await response.blob())
    const link = document.createElement('a'); link.href = href; link.download = name; link.click()
    setTimeout(() => URL.revokeObjectURL(href), 1000)
  }
  const brief = view?.briefs?.find(b => b.key === key)
  const record = view?.readiness?.slides.find(s => s.slide_key === key)
  const ready = view?.readiness
  const button = 'rounded bg-stone-800 px-3 py-2 text-sm text-white disabled:opacity-40'
  const field = 'w-full rounded border border-stone-300 p-2 text-sm'
  if (view && !view.enabled) return null
  if (!view && !error) return null
  return <section className="space-y-4 rounded-xl border border-amber-300 bg-amber-50 p-5" aria-label="Premium creative handoff">
    <h2 className="text-lg font-semibold">Premium creative production</h2>
    <p className="text-sm">Export the approved campaign and actual assets to ChatGPT. Import completed artwork here, then review product fidelity and exact copy. Automated premium rendering is closed.</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {view?.blocked && <p className="text-sm text-amber-900">Complete canonical planning/assets first: {view.blocked}</p>}
    {ready && <>
      <p className="text-sm font-medium">{ready.status} · {ready.IMPORTED_SLIDE_COUNT}/{ready.EXPECTED_SLIDE_COUNT} imported · {ready.APPROVED_SLIDE_COUNT} approved · {ready.REJECTED_SLIDE_COUNT} rejected</p>
      {!ready.canonical_handoff_current && <p className="text-sm">Export the current handoff before importing or reviewing. Changed facts, copy or assets invalidate prior approval.</p>}
      <button className={button} disabled={busy} onClick={() => act(() => download(`${base}/export`, 'HANNA_PREMIUM_CREATIVE_HANDOFF.zip'))}>Export campaign + assets + ChatGPT instruction</button>
      <label className="block text-sm">Slide to import/review
        <select className={field} value={key} onChange={e => { setKey(e.target.value); setObserved(''); setProductVisible(false); setProductFaithful(false); setFeedback(''); setImage(null) }}>
          {view?.briefs?.map(b => <option value={b.key} key={b.key}>{b.slide_number}. {b.slide_role} · {b.locale} / {b.channel}</option>)}
        </select>
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <input aria-label="Completed artwork" type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setImage(e.target.files?.[0] ?? null)} />
        <button className={button} disabled={busy || !image || !ready.canonical_handoff_current} onClick={() => act(async () => {
          const data = new FormData(); data.set('image', image!); data.set('slide_key', key); data.set('expected_version', String(ready.version))
          await checked(`${base}/import`, { method: 'POST', body: data }); setObserved(''); setProductVisible(false); setProductFaithful(false)
        })}>Import for human review</button>
      </div>
      {record && <div className="space-y-3 border-t border-amber-200 pt-4">
        <p className="break-all text-xs">{record.filename} · {record.approval_status} · {record.qa_status}<br />{record.creation_source}<br />SHA256: {record.sha256}</p>
        <a className="text-sm underline" target="_blank" rel="noreferrer" href={`${base}/preview?slide_key=${encodeURIComponent(key)}&version=${ready.version}`}>Open imported artwork for visual inspection</a>
        <p className="text-sm">Approved copy (transcribe the artwork below; no OCR or aesthetic score grants approval):</p>
        <pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(Object.fromEntries(brief?.approved_copy.map(c => [c.key, c.text]) ?? []), null, 2)}</pre>
        <input className={field} aria-label="Reviewer name" placeholder="Reviewer name" value={reviewer} onChange={e => setReviewer(e.target.value)} />
        <label className="block text-sm"><input type="checkbox" checked={productVisible} onChange={e => setProductVisible(e.target.checked)} /> I inspected this image: the expected product is visible.</label>
        <label className="block text-sm"><input type="checkbox" checked={productFaithful} onChange={e => setProductFaithful(e.target.checked)} /> Product, variant and packaging match the canonical assets.</label>
        <textarea className={field} aria-label="Observed artwork copy JSON" placeholder="Transcribe visible copy as a JSON object using the approved keys" value={observed} onChange={e => setObserved(e.target.value)} rows={4} />
        <label className="block text-sm">Revision reason<select className={field} value={reason} onChange={e => setReason(e.target.value)}>{reasons.map(r => <option key={r}>{r}</option>)}</select></label>
        <textarea className={field} aria-label="Requested visual changes" placeholder="Exact rejection reasons and requested visual changes" value={feedback} onChange={e => setFeedback(e.target.value)} rows={3} />
        <div className="flex flex-wrap gap-3">
          {(['APPROVED', 'REJECTED'] as const).map(decision => <button key={decision} className={button} disabled={busy || !reviewer.trim() || (decision === 'APPROVED' ? !productVisible || !productFaithful || !observed.trim() : !feedback.trim())} onClick={() => act(async () => {
            await checked(`${base}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_version: ready.version, slide_key: key, decision, reviewer, product_visible: productVisible, product_fidelity_confirmed: productFaithful, observed_copy: decision === 'APPROVED' ? JSON.parse(observed) : {}, feedback_codes: decision === 'REJECTED' ? [reason] : [], feedback }) })
          })}>{decision === 'APPROVED' ? 'Approve inspected artwork' : 'Reject with feedback'}</button>)}
          {record.approval_status === 'REJECTED' && <button className={button} disabled={busy} onClick={() => act(() => download(`${base}/revision?slide_key=${encodeURIComponent(key)}`, 'HANNA_SLIDE_REVISION.zip'))}>Export this slide’s revision handoff</button>}
        </div>
      </div>}
    </>}
  </section>
}
