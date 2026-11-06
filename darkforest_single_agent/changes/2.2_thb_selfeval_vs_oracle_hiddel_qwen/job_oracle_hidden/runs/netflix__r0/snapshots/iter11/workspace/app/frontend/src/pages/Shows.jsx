import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import Hero from '../components/Hero'
import Rail from '../components/Rail'
import { useFetch, topN, newest, pickHero } from '../lib/hooks'

export default function Shows() {
  const nav = useNavigate()
  const { data: titles, loading } = useFetch('/api/titles?kind=series')
  const { data: genres, loading: gLoading } = useFetch('/api/genres')

  const pool = useMemo(() => titles || [], [titles])
  const hero = useMemo(() => pickHero(pool), [pool])
  const topPicks = useMemo(() => topN(pool, 12), [pool])
  const newShows = useMemo(() => newest(pool, 12), [pool])
  const sciFi = pool.filter((t) => ['Sci-Fi & Fantasy', 'Science Fiction', 'Fantasy', 'Mystery'].includes(t.genre))
  const comedy = pool.filter((t) => t.genre === 'Comedy')

  if (loading || gLoading) return <div className="page-pad" style={{ minHeight: '100vh' }} />

  const genreOptions = (genres || []).filter((g) => pool.some((t) => (t.genres || [t.genre]).includes(g.name)))

  return (
    <div style={{ minHeight: '100vh' }}>
      <Header />
      {hero && <Hero title={hero} />}
      <div style={{ marginTop: -30, position: 'relative', zIndex: 5, padding: '10px 0 40px' }}>
        <div className="section-head" style={{ padding: '0 4vw' }}>
          <h1>TV Shows</h1>
          <select
            className="filter-select"
            aria-label="Filter by genre"
            value=""
            onChange={(e) => e.target.value && nav(`/browse/genre/${e.target.value}`)}
          >
            <option value="">Genres</option>
            {genreOptions.map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
        </div>
        <Rail title="Today’s Top Picks" items={topPicks} emptyText="No series available yet." />
        <Rail title="New TV Shows" items={newShows} emptyText="No new series yet." />
        {sciFi.length > 0 && <Rail title="Sci-Fi & Fantasy" items={sciFi} emptyText="—" />}
        {comedy.length > 0 && <Rail title="Comedies" items={comedy} emptyText="—" />}
      </div>
    </div>
  )
}
