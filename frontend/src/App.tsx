import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { BrandProvider } from './components/BrandContext'
import Overview from './pages/Overview'
import Onboarding from './pages/Onboarding'
import Library from './pages/Library'
import SettingsPage from './pages/Settings'
import Brands from './pages/Brands'
import BrandDetail from './pages/BrandDetail'
import Campaigns from './pages/Campaigns'
import CampaignDetail from './pages/CampaignDetail'
import Research from './pages/Research'
import StrategyLibrary from './pages/StrategyLibrary'
import Defense from './pages/Defense'
import Opportunities from './pages/Opportunities'
import Analytics from './pages/Analytics'
import CalendarPage from './pages/Calendar'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15_000 } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrandProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="onboarding" element={<Onboarding />} />
              <Route path="campaigns" element={<Campaigns />} />
              <Route path="campaigns/:campaignId" element={<CampaignDetail />} />
              <Route path="strategy-library" element={<StrategyLibrary />} />
              <Route path="defense" element={<Defense />} />
              <Route path="library" element={<Library />} />
              <Route path="brands" element={<Brands />} />
              <Route path="brands/:brandId" element={<BrandDetail />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="research" element={<Research />} />
              <Route path="opportunities" element={<Opportunities />} />
              <Route path="calendar" element={<CalendarPage />} />
              <Route path="analytics" element={<Analytics />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </BrandProvider>
    </QueryClientProvider>
  )
}
