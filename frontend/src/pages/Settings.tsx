import { useEffect, useState } from 'react'
import { useSettings, useUpdateSettings } from '../api/hooks'
import { Button, Card, Input, Label } from '../components/ui'

export default function SettingsPage() {
  const { data: settings } = useSettings()
  const update = useUpdateSettings()

  const [form, setForm] = useState({
    source_asset_root: '',
    output_root: '',
    openai_api_key: '',
    openai_research_model: '',
    openai_campaign_model: '',
    openai_vision_model: '',
    openai_image_model: '',
    facebook_page_id: '',
    facebook_page_access_token: '',
    instagram_business_account_id: '',
    public_base_url: '',
  })

  useEffect(() => {
    if (settings) {
      setForm((f) => ({
        ...f,
        source_asset_root: settings.source_asset_root,
        output_root: settings.output_root,
        openai_research_model: settings.openai_research_model,
        openai_campaign_model: settings.openai_campaign_model,
        openai_vision_model: settings.openai_vision_model,
        openai_image_model: settings.openai_image_model,
        facebook_page_id: settings.facebook_page_id,
        instagram_business_account_id: settings.instagram_business_account_id,
        public_base_url: settings.public_base_url,
      }))
    }
  }, [settings])

  const save = () => {
    const payload = { ...form }
    if (!payload.openai_api_key) delete (payload as Record<string, unknown>).openai_api_key
    if (!payload.facebook_page_access_token) delete (payload as Record<string, unknown>).facebook_page_access_token
    update.mutate(payload)
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-stone-500">Repositories and AI provider configuration.</p>
      </div>

      <Card className="space-y-4 p-5">
        <h2 className="text-sm font-semibold">Repositories</h2>
        <div>
          <Label>Source asset root (read-only, never modified)</Label>
          <Input
            placeholder={String.raw`C:\Marketing\Source`}
            value={form.source_asset_root}
            onChange={(e) => setForm({ ...form, source_asset_root: e.target.value })}
          />
        </div>
        <div>
          <Label>Output root</Label>
          <Input
            placeholder={String.raw`C:\Marketing\Generated`}
            value={form.output_root}
            onChange={(e) => setForm({ ...form, output_root: e.target.value })}
          />
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <h2 className="text-sm font-semibold">AI provider (OpenAI)</h2>
        <div>
          <Label>
            API key {settings?.openai_configured && <span className="text-emerald-600">· configured</span>}
          </Label>
          <Input
            type="password"
            placeholder={settings?.openai_configured ? '••••••••••••••••' : 'sk-...'}
            value={form.openai_api_key}
            onChange={(e) => setForm({ ...form, openai_api_key: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Research model</Label>
            <Input value={form.openai_research_model} onChange={(e) => setForm({ ...form, openai_research_model: e.target.value })} />
          </div>
          <div>
            <Label>Campaign model</Label>
            <Input value={form.openai_campaign_model} onChange={(e) => setForm({ ...form, openai_campaign_model: e.target.value })} />
          </div>
          <div>
            <Label>Vision model</Label>
            <Input value={form.openai_vision_model} onChange={(e) => setForm({ ...form, openai_vision_model: e.target.value })} />
          </div>
          <div>
            <Label>Image model</Label>
            <Input value={form.openai_image_model} onChange={(e) => setForm({ ...form, openai_image_model: e.target.value })} />
          </div>
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <div>
          <h2 className="text-sm font-semibold">Facebook Page / Instagram auto-publish</h2>
          <p className="mt-1 text-xs text-stone-500">
            Lets Campaign Detail's "Publish now" button actually post a rendered creative to your own Page/
            Instagram Business account via Meta's Graph API. See the README's "Facebook Page / Instagram
            auto-publish" section for how to get a Page access token, Page ID, and Instagram Business Account ID.
          </p>
        </div>
        <div>
          <Label>
            Facebook Page access token{' '}
            {settings?.facebook_configured && <span className="text-emerald-600">· configured</span>}
          </Label>
          <Input
            type="password"
            placeholder={settings?.facebook_configured ? '••••••••••••••••' : 'EAAG...'}
            value={form.facebook_page_access_token}
            onChange={(e) => setForm({ ...form, facebook_page_access_token: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Facebook Page ID</Label>
            <Input
              value={form.facebook_page_id}
              onChange={(e) => setForm({ ...form, facebook_page_id: e.target.value })}
            />
          </div>
          <div>
            <Label>Instagram Business Account ID</Label>
            <Input
              value={form.instagram_business_account_id}
              onChange={(e) => setForm({ ...form, instagram_business_account_id: e.target.value })}
            />
          </div>
        </div>
        <div>
          <Label>Public base URL (Instagram only)</Label>
          <Input
            placeholder="https://your-tunnel.ngrok.app"
            value={form.public_base_url}
            onChange={(e) => setForm({ ...form, public_base_url: e.target.value })}
          />
          <p className="mt-1 text-xs text-stone-400">
            Instagram's API fetches the image itself and can't accept a direct upload, so it needs a URL Meta's
            servers can reach — a tunnel (e.g. ngrok) pointed at this backend. Not needed for Facebook Page
            posts, which upload the file directly.
          </p>
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={update.isPending}>
          {update.isPending ? 'Saving…' : 'Save settings'}
        </Button>
        {update.isSuccess && <span className="text-sm text-emerald-600">Saved.</span>}
      </div>
    </div>
  )
}
