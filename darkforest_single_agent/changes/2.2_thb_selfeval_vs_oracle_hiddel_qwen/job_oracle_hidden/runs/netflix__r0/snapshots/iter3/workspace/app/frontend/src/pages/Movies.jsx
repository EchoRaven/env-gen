import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import Hero from '../components/Hero'
import Rail from '../components/Rail'
import { useFetch, topN, newest, pickHero } from '../lib/hooks'

export default function Movies() {
  const nav = useNavigate()
  const { data: titles, loading } = useFetch('/api/titles?kind=movie')
  const { data: genres, loading: gLoading } = useFetch('/api/genres')

  const pool = useMemo(() => titles || [], [titles])
  const hero = useMemo(() => pickHero(pool), [pool])
  const gems = useMemo(() => topN(pool, 12), [pool])
  const newMovies = useMemo(() => newest(pool, 12), [pool])
  const horror = pool.filter((t) => t.genre === 'Horror')
  const drama = pool.filter((t) => t.genre === 'Drama')

  if (loading || gLoading) return <div className="page-pad" style={{ minHeight: '100vh' }} />

  const genreOptions = (genres || []).filter((g) => pool.some((t) => (t.genres || [t.genre]).includes(g.name)))

  return (
    <div style={{ minHeight: '100vh' }}>
      <Header />
      {hero && <Hero title={hero} />}
      <div style={{ marginTop: -30, position: 'relative', zIndex: 5, padding: '10px 0 40px' }}>
        <div className="section-head" style={{ padding: '0 4vw' }}>
          <h1>Movies</h1>
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
        <Rail title="Gems for You" items={gems} emptyText="No movies available yet." />
        <Rail title="New Movies" items={newMovies} emptyText="No new movies yet." />
        {horror.length > 0 && <Rail title="Horror Movies" items={horror} emptyText="—" />}
        {drama.length > 0 && <Rail title="Dramas" items={drama} emptyText="—" />}
      </div>
    </div>
  )
}
