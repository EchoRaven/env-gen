import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

export function useTitleOverlay() {
  const [params, setParams] = useSearchParams()
  const openTitle = useCallback((title) => {
    if (!title) return
    const next = new URLSearchParams(params)
    next.set('title', String(title.id))
    setParams(next)
  }, [params, setParams])
  return { openTitle }
}
