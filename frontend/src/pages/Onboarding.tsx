import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Rocket } from 'lucide-react'
import { useBrand } from '../components/BrandContext'
import { useBrands, useCreateBrand, useScanRepository, useSettings, useUpdateSettings } from '../api/hooks'
import { Badge, Button, Card, Input, Label } from '../components/ui'

function slugify(name: string) {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

const STEPS = ['Brand', 'Repositories & AI key', 'Scan your photos', 'Done']

/** First-run setup wizard: create a brand workspace, point it at a real source-
 * photo folder and output folder plus an OpenAI key, scan the source folder once
 * so there are actual assets to build campaigns from, then hand off to the normal
 * app. Every step here calls the same hooks/endpoints the standalone Brands/
 * Settings/Library pages already use (useCreateBrand, useUpdateSettings,
 * useScanRepository) — this page just sequences them into one guided flow instead
 * of a new user having to discover those three separate pages on their own.
 * Revisitable any time from the sidebar's "Setup guide" link, not just on first
 * run — e.g. to add a second brand or point at a different source folder later. */
export default function Onboarding() {
  const navigate = useNavigate()
  const { brandId: activeBrandId, setBrandId } = useBrand()
  const { data: brands } = useBrands()
  const createBrand = useCreateBrand()
  const { data: settings } = useSettings()
  const updateSettings = useUpdateSettings()
  const scanRepository = useScanRepository()

  const [step, setStep] = useState(0)
  const [wizardBrandId, setWizardBrandId] = useState<string | undefined>(undefined)
  const [brandName, setBrandName] = useState('')

  const [sourceRoot, setSourceRoot] = useState('')
  const [outputRoot, setOutputRoot] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')

  useEffect(() => {
    if (settings) {
      setSourceRoot(settings.source_asset_root || '')
      setOutputRoot(settings.output_root || '')
    }
  }, [settings])

  const brand = brands?.find((b) => b.id === wizardBrandId)
  const sourceConfigured = !!(settings?.source_asset_root || sourceRoot).trim()

  function goToStep1WithExistingBrand(id: string) {
    setWizardBrandId(id)
    setBrandId(id)
    setStep(1)
  }

  function createAndContinue() {
    const name = brandName.trim()
    if (!name) return
    createBrand.mutate(
      { name, slug: slugify(name) },
      {
        onSuccess: (created) => {
          setWizardBrandId(created.id)
          setBrandId(created.id)
          setStep(1)
        },
      },
    )
  }

  function saveSettingsAndContinue() {
    const payload: { source_asset_root: string; output_root: string; openai_api_key?: string } = {
      source_asset_root: sourceRoot,
      output_root: outputRoot,
    }
    if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim()
    updateSettings.mutate(payload, { onSuccess: () => setStep(2) })
  }

  function finish() {
    navigate('/')
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Rocket size={20} className="text-amber-600" /> Setup guide
        </h1>
        <p className="mt-1 text-sm text-stone-500">
          Four quick steps to go from a blank install to a brand ready for Autopilot.
        </p>
      </div>

      <div className="flex items-center gap-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex flex-1 items-center gap-2">
            <div
              className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-medium ${
                i < step
                  ? 'bg-emerald-600 text-white'
                  : i === step
                    ? 'bg-stone-900 text-white'
                    : 'bg-stone-100 text-stone-400'
              }`}
            >
              {i < step ? <Check size={12} /> : i + 1}
            </div>
            <span className={`text-xs ${i === step ? 'font-medium text-stone-800' : 'text-stone-400'}`}>{label}</span>
            {i < STEPS.length - 1 && <div className="h-px flex-1 bg-stone-200" />}
          </div>
        ))}
      </div>

      {step === 0 && (
        <Card className="space-y-4 p-5">
          <div>
            <h2 className="text-sm font-semibold text-stone-800">Create a brand workspace</h2>
            <p className="mt-1 text-xs text-stone-500">
              Everything else — photos, campaigns, voice & visual style — lives under one brand. One workspace per
              business; you can add more later from the Brands page.
            </p>
          </div>
          <div>
            <Label>Brand name</Label>
            <div className="flex gap-2">
              <Input value={brandName} onChange={(e) => setBrandName(e.target.value)} placeholder="Hanna Japan Store" />
              <Button disabled={!brandName.trim() || createBrand.isPending} onClick={createAndContinue}>
                {createBrand.isPending ? 'Creating…' : 'Create & continue'}
              </Button>
            </div>
            {createBrand.isError && (
              <p className="mt-2 text-xs text-red-700">{(createBrand.error as Error).message}</p>
            )}
          </div>

          {brands && brands.length > 0 && (
            <div className="border-t border-stone-100 pt-3">
              <p className="mb-2 text-xs text-stone-500">Or continue setting up an existing brand:</p>
              <div className="space-y-1.5">
                {brands.map((b) => (
                  <button
                    key={b.id}
                    onClick={() => goToStep1WithExistingBrand(b.id)}
                    className="flex w-full items-center justify-between rounded-lg border border-stone-200 px-3 py-2 text-left text-sm hover:bg-stone-50"
                  >
                    <span>{b.name}</span>
                    <span className="text-xs text-stone-400">{b.slug} →</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {step === 1 && (
        <Card className="space-y-4 p-5">
          <div>
            <h2 className="text-sm font-semibold text-stone-800">Point it at your files</h2>
            <p className="mt-1 text-xs text-stone-500">
              Source is where your real product photos already live — never modified. Output is where recreated
              marketing images get written. An OpenAI key unlocks research, copy, and Autopilot; you can skip it and
              add it later in Settings, but nothing AI-powered will run until it's set.
            </p>
          </div>
          <div>
            <Label>Source photo folder</Label>
            <Input
              placeholder={String.raw`C:\Marketing\Source`}
              value={sourceRoot}
              onChange={(e) => setSourceRoot(e.target.value)}
            />
          </div>
          <div>
            <Label>Output folder</Label>
            <Input
              placeholder={String.raw`C:\Marketing\Generated`}
              value={outputRoot}
              onChange={(e) => setOutputRoot(e.target.value)}
            />
          </div>
          <div>
            <Label>
              OpenAI API key {settings?.openai_configured && <span className="text-emerald-600">· already configured</span>}
            </Label>
            <Input
              type="password"
              placeholder={settings?.openai_configured ? '••••••••••••••••' : 'sk-... (optional for now)'}
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-3 pt-1">
            <Button variant="ghost" onClick={() => setStep(0)}>
              Back
            </Button>
            <Button disabled={!sourceRoot.trim() || !outputRoot.trim() || updateSettings.isPending} onClick={saveSettingsAndContinue}>
              {updateSettings.isPending ? 'Saving…' : 'Save & continue'}
            </Button>
          </div>
          {updateSettings.isError && (
            <p className="text-xs text-red-700">{(updateSettings.error as Error).message}</p>
          )}
        </Card>
      )}

      {step === 2 && (
        <Card className="space-y-4 p-5">
          <div>
            <h2 className="text-sm font-semibold text-stone-800">Scan your photo library</h2>
            <p className="mt-1 text-xs text-stone-500">
              Indexes every photo under your source folder into {brand ? brand.name : 'this brand'}'s asset library —
              organized by whatever subfolders you already use (e.g. Skincare/, Coffee Shop/). Nothing under that
              folder is ever modified; the scanner only reads it. You can re-run this any time from the Library page
              as you add more photos.
            </p>
          </div>
          <Button
            disabled={!sourceConfigured || scanRepository.isPending || !wizardBrandId}
            onClick={() => wizardBrandId && scanRepository.mutate(wizardBrandId, { onSuccess: () => setStep(3) })}
          >
            {scanRepository.isPending ? 'Scanning…' : 'Scan now'}
          </Button>
          {!sourceConfigured && (
            <p className="text-xs text-amber-700">Go back and set a source photo folder first.</p>
          )}
          {scanRepository.isError && (
            <p className="text-xs text-red-700">{(scanRepository.error as Error).message}</p>
          )}
          <div className="flex items-center gap-3 pt-1">
            <Button variant="ghost" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button variant="ghost" onClick={() => setStep(3)}>
              Skip for now
            </Button>
          </div>
        </Card>
      )}

      {step === 3 && (
        <Card className="space-y-4 p-5 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
            <Check size={22} />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-stone-800">You're set up</h2>
            <p className="mt-1 text-xs text-stone-500">
              {brand ? brand.name : 'Your brand'} is ready.
              {scanRepository.data
                ? ` Scanned ${scanRepository.data.scanned_files} file(s) — ${scanRepository.data.new_assets} new asset(s) indexed.`
                : ' Add photos and scan from the Library page whenever you\'re ready.'}
              {!settings?.openai_configured && ' Add an OpenAI key in Settings to unlock research, copy, and Autopilot.'}
            </p>
          </div>
          <div className="flex items-center justify-center gap-3 pt-1">
            <Button onClick={finish}>Go to Overview</Button>
            {wizardBrandId && (
              <Button variant="secondary" onClick={() => navigate(`/brands/${wizardBrandId}`)}>
                Set brand voice & style
              </Button>
            )}
          </div>
        </Card>
      )}

      {activeBrandId && activeBrandId !== wizardBrandId && step === 0 && (
        <p className="text-center text-xs text-stone-400">
          Currently working in <Badge tone="muted">{brands?.find((b) => b.id === activeBrandId)?.name}</Badge> — this
          guide won't change that until you create or pick a brand above.
        </p>
      )}
    </div>
  )
}
