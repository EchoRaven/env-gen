import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import PosterRail from '../components/PosterRail.jsx'
import { useTitleOverlay } from '../components/useTitleOverlay.js'

export default function NewAndPopularPage() {
  const { api } = useAuth()
  const { openTitle } = useTitleOverlay()
  const [newTitles, setNewTitles] = useState([])
  const [topSeries, setTopSeries] = useState([])
  const [topMovies, setTopMovies] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.get('/api/titles?sort=new&limit=30'),
      api.get('/api/titles/top10?kind=series'),
      api.get('/api/titles/top10?kind=movie'),
    ]).then(([newest, series, movies]) => {
      if (cancelled) return
      setNewTitles(newest.items || [])
      setTopSeries(series.items || [])
      setTopMovies(movies.items || [])
    }).catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [api])

  return (
    <PageShell className="browse-app">
      <div className="browse-main">
        {loading && <div className="page-loading">Loading new and popular titles…</div>}
        {error && <div className="page-error">{error}</div>}
        <div className="browse-rows new-popular-rows">
          <PosterRail title="New on Netflix" items={newTitles} onOpen={openTitle} />
          <PosterRail title="Top 10 TV Shows in the U.S. Today" items={topSeries} onOpen={openTitle} variant="top10" />
          <PosterRail title="Top 10 Movies in the U.S. Today" items={topMovies} onOpen={openTitle} variant="top10" />
          <PosterRail title="Coming This Week" items={[]} onOpen={openTitle} showEmpty />
        </div>
      </div>
    </PageShell>
  )
}
