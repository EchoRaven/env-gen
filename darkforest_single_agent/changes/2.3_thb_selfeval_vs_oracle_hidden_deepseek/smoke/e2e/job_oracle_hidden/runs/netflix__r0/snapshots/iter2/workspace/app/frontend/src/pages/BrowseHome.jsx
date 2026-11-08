import React, { useEffect, useState } from 'react'
import { api } from '../api'
import Hero from '../components/Hero'
import Row from '../components/Row'
import { ErrorState, LoadingPage } from '../components/PageUtilities'
import { useOpenTitle } from '../hooks'

export default function BrowseHome() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)
  const openTitle = useOpenTitle()

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      api('/api/titles/trending'),
      api('/api/continue-watching'),
      api('/api/genres'),
      api('/api/titles?kind=series&limit=60'),
      api('/api/titles?kind=movie&limit=60'),
      api('/api/titles?year=2026&limit=30'),
    ]).then(([trending, continueWatching, genres, series, movies, newTitles]) => {
      if (cancelled) return
      setData({ trending, continueWatching, genres, series, movies, newTitles })
    }).catch(err => {
      if (!cancelled) setError(err.message)
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [nonce])

  if (loading) return <LoadingPage label="Loading your Netflix…" />
  if (error) return <ErrorState message={error} onRetry={() => setNonce(value => value + 1)} />

  const trending = data?.trending || []
  const continueWatching = data?.continueWatching || []
  const actionGenre = data?.genres?.find(item => /action & adventure/i.test(item.name))
  const actionShows = data?.series?.filter(item => item.genres?.includes('Action & Adventure')) || []
  const onlyNetflix = [...(data?.series || []), ...(data?.movies || [])].filter(item => item.rating >= 8).slice(0, 20)
  const topSearches = [...(data?.trending || []), ...(data?.newTitles || [])].filter((item, index, arr) => arr.findIndex(x => x.id === item.id) === index).slice(0, 20)

  return (
    <div className="browse-page">
      <Hero title={trending[0]} eyebrow="Featured" />
      <div className="rows-container">
        <Row title="Trending Now" titles={trending} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Continue Watching for You" titles={continueWatching} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} kind="continue" />
        <Row title="TV Action & Adventure" titles={actionShows} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Games" titles={[]} onOpen={openTitle} />
        <Row title="Only on Netflix" titles={onlyNetflix} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Top Searches" titles={topSearches} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="New on Netflix" titles={data?.newTitles || []} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
      </div>
    </div>
  )
}
