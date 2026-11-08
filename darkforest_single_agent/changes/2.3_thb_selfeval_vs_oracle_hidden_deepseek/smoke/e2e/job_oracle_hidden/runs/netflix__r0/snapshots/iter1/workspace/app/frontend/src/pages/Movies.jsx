import React, { useEffect, useState } from 'react'
import { api } from '../api'
import Hero from '../components/Hero'
import Row from '../components/Row'
import { GenreDropdown, LoadingPage, ErrorState } from '../components/PageUtilities'
import { useOpenTitle } from '../hooks'

export default function Movies() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)
  const openTitle = useOpenTitle()

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api('/api/titles?kind=movie&limit=60'),
      api('/api/titles/trending?kind=movie'),
      api('/api/genres?kind=movie'),
      api('/api/titles?kind=movie&year=2026&limit=30'),
    ]).then(([all, trending, genres, newest]) => setData({ all, trending, genres, newest }))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [nonce])

  if (loading) return <LoadingPage label="Loading movies…" />
  if (error) return <ErrorState message={error} onRetry={() => setNonce(v => v + 1)} />
  const all = data?.all || []
  const picks = [...all].sort((a, b) => b.rating - a.rating).slice(0, 18)
  const action = all.filter(item => item.genres?.some(g => /action|adventure/i.test(g)))
  const comedy = all.filter(item => item.genres?.includes('Comedy'))
  const scifi = all.filter(item => item.genres?.some(g => /science fiction|fantasy/i.test(g)))

  return (
    <div className="browse-page section-page">
      <Hero title={data?.trending?.[0] || all[0]} eyebrow="Movies" />
      <div className="section-controls"><h1>Movies</h1><GenreDropdown genres={data?.genres || []} kindLabel="Movies" /></div>
      <div className="rows-container raised">
        <Row title="Gems for You" titles={picks} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Trending Movies" titles={data?.trending || []} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Action & Adventure Movies" titles={action} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Comedies" titles={comedy} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Sci-Fi & Fantasy Movies" titles={scifi} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="New Movies" titles={data?.newest || []} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
      </div>
    </div>
  )
}
