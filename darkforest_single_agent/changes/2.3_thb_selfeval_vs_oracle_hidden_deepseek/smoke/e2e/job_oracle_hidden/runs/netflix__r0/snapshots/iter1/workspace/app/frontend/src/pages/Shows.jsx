import React, { useEffect, useState } from 'react'
import { api } from '../api'
import Hero from '../components/Hero'
import Row from '../components/Row'
import { GenreDropdown, LoadingPage, ErrorState } from '../components/PageUtilities'
import { useOpenTitle } from '../hooks'

export default function Shows() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)
  const openTitle = useOpenTitle()

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api('/api/titles?kind=series&limit=60'),
      api('/api/titles/trending?kind=series'),
      api('/api/genres?kind=series'),
      api('/api/titles?kind=series&year=2026&limit=30'),
    ]).then(([all, trending, genres, newest]) => setData({ all, trending, genres, newest }))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [nonce])

  if (loading) return <LoadingPage label="Loading TV shows…" />
  if (error) return <ErrorState message={error} onRetry={() => setNonce(v => v + 1)} />
  const all = data?.all || []
  const dramas = all.filter(item => item.genres?.includes('Drama'))
  const sciFi = all.filter(item => item.genres?.includes('Sci-Fi & Fantasy'))
  const picks = [...all].sort((a, b) => b.rating - a.rating).slice(0, 18)

  return (
    <div className="browse-page section-page">
      <Hero title={data?.trending?.[0] || all[0]} eyebrow="TV Shows" />
      <div className="section-controls"><h1>TV Shows</h1><GenreDropdown genres={data?.genres || []} kindLabel="TV Shows" /></div>
      <div className="rows-container raised">
        <Row title="Today's Top Picks for You" titles={picks} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Trending TV Shows" titles={data?.trending || []} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="TV Dramas" titles={dramas} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="TV Sci-Fi & Fantasy" titles={sciFi} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="New TV Shows" titles={data?.newest || []} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
      </div>
    </div>
  )
}
