import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import HeroBillboard from '../components/HeroBillboard.jsx'
import PosterRail from '../components/PosterRail.jsx'
import { useTitleOverlay } from '../components/useTitleOverlay.js'

export default function GenreCategoryPage() {
  const { genreId } = useParams()
  const { api } = useAuth()
  const { openTitle } = useTitleOverlay()
  const [items, setItems] = useState([])
  const [genre, setGenre] = useState(null)
  const [allGenres, setAllGenres] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([api.get(`/api/genres/${genreId}/titles`), api.get('/api/genres')])
      .then(([titles, genres]) => {
        if (cancelled) return
        setItems(titles.items || [])
        setGenre(titles.genre || null)
        setAllGenres(genres.items || [])
      })
      .catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [api, genreId])

  const movies = items.filter((item) => item.kind === 'movie')
  const series = items.filter((item) => item.kind === 'series')
  const title = genre?.name || 'Genre'
  const parentLabel = series.length && !movies.length ? 'TV Shows' : movies.length && !series.length ? 'Movies' : 'Browse'

  return (
    <PageShell className="browse-app">
      <div className="browse-main">
        {loading && <div className="page-loading">Loading {title}…</div>}
        {error && <div className="page-error">{error}</div>}
        {!loading && (
          <HeroBillboard
            title={items[0]}
            eyebrow="GENRE"
            pageLabel={title}
            onMoreInfo={openTitle}
            compact
            topBar={<div className="hero-topbar genre-hero-topbar"><span>{parentLabel}</span><h1>{title}</h1></div>}
          />
        )}
        <div className="browse-rows catalog-rows">
          <PosterRail title="Your Next Watch" items={items} onOpen={openTitle} showEmpty />
          <PosterRail title={`${title} Movies`} items={movies} onOpen={openTitle} />
          <PosterRail title={`${title} TV Shows`} items={series} onOpen={openTitle} />
          <div className="genre-chip-row">
            {allGenres.map((entry) => (
              <Link key={entry.id} to={`/browse/genre/${entry.id}`} className={`genre-chip ${String(entry.id) === String(genreId) ? 'active' : ''}`}>{entry.name}</Link>
            ))}
          </div>
        </div>
      </div>
    </PageShell>
  )
}
