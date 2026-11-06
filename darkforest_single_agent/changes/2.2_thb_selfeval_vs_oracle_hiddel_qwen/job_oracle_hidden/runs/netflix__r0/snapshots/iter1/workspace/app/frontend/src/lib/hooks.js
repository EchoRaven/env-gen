import { useEffect, useState } from 'react'
import { api } from './api'

export function useFetch(url, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let alive = true
    setLoading(true)
    api(url)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, loading }
}

export function topN(list, n) {
  return [...list]
    .filter((t) => t.rating != null)
    .sort((a, b) => b.rating - a.rating || a.id - b.id)
    .slice(0, n)
}

export function newest(list, n) {
  return [...list]
    .sort((a, b) => String(b.year).localeCompare(String(a.year)) || a.id - b.id)
    .slice(0, n)
}

// deterministic hero pick: top-rated of a pool with a backdrop
export function pickHero(pool) {
  const withBackdrop = pool.filter((t) => t.backdrop)
  const pool2 = withBackdrop.length ? withBackdrop : pool
  if (!pool2.length) return null
  return topN(pool2, 1)[0]
}
