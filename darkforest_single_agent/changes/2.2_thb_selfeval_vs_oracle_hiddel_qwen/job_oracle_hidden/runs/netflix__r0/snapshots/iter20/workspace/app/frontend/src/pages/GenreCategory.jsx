import { useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import Rail from '../components/Rail'
import { useFetch, topN } from '../lib/hooks'

export default function GenreCategory() {
  const { genreId } = useParams()
  const nav = useNavigate()
  const { data: titles, loading } = useFetch(`/api/genres/${genreId}/titles`, [genreId])
  const { data: genres, loading: gLoading } = useFetch('/api/genres')

  const pool = useMemo(() => titles || [], [titles])
  const genre = useMemo(() => (genres || []).find((g) => String(g.id) === String(genreId)), [genres, genreId])
  const series = pool.filter((t) => t.kind === 'series')
  const movies = pool.filter((t) => t.kind === 'movie')
  const top = useMemo(() => topN(pool, 12), [pool])

  if (loading || gLoading) return <div className="page-pad" style={{ minHeight: '100vh' }} />

  const label = genre?.name || 'Genre'
  const sub = series.length && movies.length ? 'Series & Films' : series.length ? 'TV Shows' : movies.length ? 'Films' : ''

  return (
    <div style={{ minHeight: '100vh' }}>
      <Header />
      <div style={{ padding: '96px 4vw 20px' }}>
        <h1 style={{ margin: 0, fontSize: 2.2 }}>{label} <span style={{ color: '#808080', fontSize: 1.4 }}>{sub}</span></h1>
        {pool.length === 0 && <p style={{ color: '#808080' }}>No titles in this genre yet.</p>}
      </div>
      <Rail title={`Top Picks in ${label}`} items={top} emptyText="No titles in this genre yet." />
      {series.length > 0 && <Rail title={`${label} TV Shows`} items={series} emptyText="—" />}
      {movies.length > 0 && <Rail title={`${label} Movies`} items={movies} emptyText="—" />}
      <div style={{ padding: '10px 4vw 40px' }}>
        <a href="#/browse" onClick={(e) => { e.preventDefault(); nav('/browse') }} style={{ color: '#e5e5e5', fontSize: 0.9 }}>
          ← Back to Home
        </a>
      </div>
    </div>
  )
}
