import React, { useEffect, useState } from 'react'
import { api } from '../api'
import Row from '../components/Row'
import { LoadingPage, ErrorState } from '../components/PageUtilities'
import { useOpenTitle } from '../hooks'

export default function NewPopular() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)
  const openTitle = useOpenTitle()

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api('/api/titles?year=2026&limit=40'),
      api('/api/titles/top10?kind=series'),
      api('/api/titles/top10?kind=movie'),
      api('/api/titles/trending'),
    ]).then(([newTitles, topShows, topMovies, trending]) => setData({ newTitles, topShows, topMovies, trending }))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [nonce])

  if (loading) return <LoadingPage label="Loading new releases…" />
  if (error) return <ErrorState message={error} onRetry={() => setNonce(v => v + 1)} />
  const newTitles = data?.newTitles || []

  return (
    <div className="browse-page new-page simple-rows-page with-kicker">
      <div className="page-kicker"><span>Browse</span><h1>New &amp; Popular</h1></div>
      <div className="rows-container raised">
        <Row title="New on Netflix" titles={newTitles} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title="Top 10 TV Shows in the U.S. Today" titles={data?.topShows || []} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} ranked kind="ranked" />
        <Row title="Top 10 Movies in the U.S. Today" titles={data?.topMovies || []} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} ranked kind="ranked" />
        <Row title="Coming This Week" titles={newTitles.slice(0, 12)} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
      </div>
    </div>
  )
}
