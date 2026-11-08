import { useSearchParams } from 'react-router-dom'
import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

export function useOpenTitle() {
  const [params, setParams] = useSearchParams()
  return useCallback((id) => {
    const next = new URLSearchParams(params)
    next.set('title', String(id))
    setParams(next)
  }, [params, setParams])
}

export function useCloseTitle() {
  const [params, setParams] = useSearchParams()
  return useCallback(() => {
    const next = new URLSearchParams(params)
    next.delete('title')
    setParams(next, { replace: true })
  }, [params, setParams])
}

export function useFetch(path, enabled = true) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(Boolean(enabled && path))
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    if (!enabled || !path) { setLoading(false); return }
    setLoading(true)
    setError('')
    api(path)
      .then(result => { if (!cancelled) setData(result) })
      .catch(err => { if (!cancelled) setError(err.message || 'Unable to load content.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [path, enabled, nonce])

  return { data, loading, error, reload: () => setNonce(value => value + 1), setData }
}
