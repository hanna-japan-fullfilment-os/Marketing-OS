import { NavLink, Outlet } from 'react-router-dom'
import {
  LayoutDashboard, Images, FlaskConical, Library, ShieldAlert, Radar, Compass, Calendar, BarChart3, Building2,
  Rocket, Settings as SettingsIcon,
} from 'lucide-react'
import clsx from 'clsx'
import { useBrands } from '../api/hooks'
import { useBrand } from './BrandContext'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, phase: null },
  { to: '/onboarding', label: 'Setup guide', icon: Rocket, phase: null },
  { to: '/campaigns', label: 'Campaigns', icon: FlaskConical, phase: null },
  { to: '/strategy-library', label: 'Strategy Library', icon: Library, phase: null },
  { to: '/defense', label: 'Defense', icon: ShieldAlert, phase: null },
  { to: '/library', label: 'Asset Library', icon: Images, phase: null },
  { to: '/research', label: 'Research', icon: Radar, phase: null },
  { to: '/opportunities', label: 'Opportunities', icon: Compass, phase: null },
  { to: '/calendar', label: 'Calendar', icon: Calendar, phase: null },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, phase: null },
  { to: '/brands', label: 'Brands', icon: Building2, phase: null },
  { to: '/settings', label: 'Settings', icon: SettingsIcon, phase: null },
]

export default function Layout() {
  const { data: brands } = useBrands()
  const { brandId, setBrandId } = useBrand()

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-stone-50 text-stone-900">
      <aside className="flex w-60 shrink-0 flex-col border-r border-stone-200 bg-white">
        <div className="px-5 py-5">
          <div className="text-sm font-semibold tracking-tight">Marketing OS</div>
          <div className="text-xs text-stone-400">local-first</div>
        </div>
        <div className="px-3 pb-3">
          <select
            value={brandId || ''}
            onChange={(e) => setBrandId(e.target.value)}
            className="w-full rounded-lg border border-stone-200 bg-stone-50 px-2 py-1.5 text-sm"
          >
            <option value="" disabled>
              Select brand…
            </option>
            {brands?.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        <nav className="flex-1 space-y-0.5 px-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                clsx(
                  'flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium',
                  isActive ? 'bg-stone-900 text-white' : 'text-stone-600 hover:bg-stone-100',
                )
              }
            >
              <span className="flex items-center gap-2.5">
                <item.icon size={16} />
                {item.label}
              </span>
              {item.phase && (
                <span className="rounded-full bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-400">
                  {item.phase}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-stone-100 px-4 py-3 text-[11px] text-stone-400">
          Hanna Japan Store · v0.1.0
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
