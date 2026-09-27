import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useBrands, useCreateBrand } from '../api/hooks'
import { Button, Card, EmptyState, Input, Label } from '../components/ui'

function slugify(name: string) {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

export default function Brands() {
  const { data: brands } = useBrands()
  const create = useCreateBrand()
  const [name, setName] = useState('')

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Brand workspaces</h1>
        <p className="text-sm text-stone-500">
          One workspace per business — Hanna Japan Store today, room for more later.
        </p>
      </div>

      <Card className="space-y-3 p-5">
        <Label>New brand name</Label>
        <div className="flex gap-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Hanna Japan Store" />
          <Button
            disabled={!name.trim() || create.isPending}
            onClick={() => {
              create.mutate({ name: name.trim(), slug: slugify(name) })
              setName('')
            }}
          >
            Create
          </Button>
        </div>
      </Card>

      {!brands || brands.length === 0 ? (
        <EmptyState title="No brands yet" description="Create your first brand workspace above." />
      ) : (
        <div className="space-y-2">
          {brands.map((b) => (
            <Link key={b.id} to={`/brands/${b.id}`}>
              <Card className="flex items-center justify-between p-4 hover:border-stone-300">
                <div>
                  <div className="text-sm font-medium">{b.name}</div>
                  <div className="text-xs text-stone-400">{b.slug}</div>
                </div>
                <span className="text-xs text-stone-400">Voice, logo & visual style →</span>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
