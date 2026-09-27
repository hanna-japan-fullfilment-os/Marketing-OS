import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useBrands } from '../api/hooks'

interface BrandContextValue {
  brandId: string | undefined
  setBrandId: (id: string) => void
}

const BrandContext = createContext<BrandContextValue>({ brandId: undefined, setBrandId: () => {} })

const STORAGE_KEY = 'marketing-os.selectedBrandId'

export function BrandProvider({ children }: { children: ReactNode }) {
  const [brandId, setBrandIdState] = useState<string | undefined>(
    () => localStorage.getItem(STORAGE_KEY) || undefined,
  )
  const { data: brands } = useBrands()

  useEffect(() => {
    if (!brandId && brands && brands.length > 0) {
      setBrandIdState(brands[0].id)
    }
  }, [brands, brandId])

  const setBrandId = (id: string) => {
    setBrandIdState(id)
    localStorage.setItem(STORAGE_KEY, id)
  }

  return <BrandContext.Provider value={{ brandId, setBrandId }}>{children}</BrandContext.Provider>
}

export function useBrand() {
  return useContext(BrandContext)
}
