import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from './PageShell.jsx'
import HeroBillboard from './HeroBillboard.jsx'
import PosterRail from './PosterRail.jsx'
import GenreMenu from './GenreMenu.jsx'
import { useTitleOverlay } from './useTitleOverlay.js'

export default function CatalogLanding({ kind, pageHeading, eyebrow, rails }) {
  const { api } = useAuth()
  const { openTitle } = useTitleOverlay()
  const [all, setAll] = useState([])
  const [top, setTop] = useState([])
  const [railData, setRailData] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      api.get(`/api/titles?kind=${kind}&limit=100&sort=rating`),
      api.get(`/api/titles/top10?kind=${kind}`),
      ...rails.map((rail) => api.get(rail.path)),
    ]).then(([allResult, topResult, ...railResults]) => {
      if (cancelled) return
      setAll(allResult.items || [])
      setTop(topResult.items || [])
      const next = {}
      rails.forEach((rail, index) => { next[rail.key] = railResults[index].items || [] })
      setRailData(next)
    }).catch((err) => {
      if (!cancelled) setError(err.message)
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [api, kind, rails])

  const hero = top[0] || all[0]

  return (
    <PageShell className="browse-app">
      <div className="browse-main">
        {loading && <div className="page-loading">Loading the catalog…</div>}
        {error && <div className="page-error">{error}</div>}
        {!loading && (
          <HeroBillboard
            title={hero}
            eyebrow="NETFLIX"
            pageLabel={pageHeading}
            onMoreInfo={openTitle}
            compact
            topBar={<div className="hero-topbar"><h1>{pageHeading}</h1><GenreMenu /></div>}
          />
        )}
        <div className="browse-rows catalog-rows">
          <PosterRail title={kind === 'series' ? "Today's Top Picks for You" : 'Gems for You'} items={top} onOpen={openTitle} />
          {rails.map((rail) => (
            <PosterRail key={rail.key} title={rail.title} items={railData[rail.key] || []} onOpen={openTitle} showEmpty={rail.showEmpty} />
          ))}
        </div>
      </div>
    </PageShell>
  )
}
