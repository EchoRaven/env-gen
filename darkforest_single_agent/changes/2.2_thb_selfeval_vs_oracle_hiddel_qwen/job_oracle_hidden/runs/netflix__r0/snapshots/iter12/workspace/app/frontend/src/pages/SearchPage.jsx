import { useSearchParams } from 'react-router-dom'
import Header from '../components/Header'
import { useFetch } from '../lib/hooks'
import { mediaUrl } from '../lib/util'
import { openTitleModal } from '../lib/modalStore'

export default function SearchPage() {
  const [params] = useSearchParams()
  const q = (params.get('q') || '').trim()
  const { data: results, loading } = useFetch(q ? `/api/search?q=${encodeURIComponent(q)}` : '/api/search', [q])

  return (
    <div className="grid-page">
      <Header />
      <h1>
        {q ? <>Results for “{q}”</> : 'Search'}
      </h1>
      {!q && <p style={{ color: '#808080' }}>Use the search icon in the header to find titles by name or genre.</p>}
      {loading && q && <p style={{ color: '#808080' }}>Searching…</p>}
      {q && !loading && (!results || results.length === 0) && (
        <p style={{ color: '#808080' }}>No titles match “{q}”. Try a different name or genre.</p>
      )}
      {results && results.length > 0 && (
        <div className="poster-grid">
          {results.map((t) => (
            <div key={t.id} className="card grid-card" onClick={() => openTitleModal(t.id)}>
              <img className="card-poster" src={mediaUrl(t.poster)} alt={t.name} loading="lazy" />
              <div className="card-name">{t.name}</div>
              <div style={{ fontSize: 0.75, color: '#a3a3a3', padding: '0 2px' }}>{t.year} · {t.genre || '—'}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
