import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import { useFetch } from '../lib/hooks'
import { mediaUrl } from '../lib/util'
import { useApp } from '../state/AppContext'
import { openTitleModal } from '../lib/modalStore'
import Icon from '../components/Icon'

export default function MyListPage() {
  const nav = useNavigate()
  const { removeFromList, myListIds } = useApp()
  const { data: items, loading } = useFetch('/api/my-list', [myListIds.size])

  if (loading) return <div className="grid-page"><h1>My List</h1><p style={{ color: '#808080' }}>Loading…</p></div>

  return (
    <div className="grid-page">
      <Header />
      <h1>My List</h1>
      {!items || items.length === 0 ? (
        <div style={{ color: '#808080', fontSize: 1.05 }}>
          Your list is empty. Add titles with the + button on any poster to save them here.
          <div style={{ marginTop: 16 }}>
            <button className="btn btn-red" style={{ padding: '10px 20px', fontSize: '0.95rem' }} onClick={() => nav('/browse')}>
              Browse titles
            </button>
          </div>
        </div>
      ) : (
        <div className="poster-grid">
          {items.map((t) => (
            <div key={t.id} className="card grid-card" onClick={() => openTitleModal(t.id)}>
              <img className="card-poster" src={mediaUrl(t.poster)} alt={t.name} loading="lazy" />
              <button
                className="grid-remove"
                aria-label={`Remove ${t.name} from My List`}
                onClick={(e) => { e.stopPropagation(); removeFromList(t.id).catch(() => {}) }}
              >
                <Icon name="close" size={14} />
              </button>
              <div className="card-name">{t.name}</div>
              <div style={{ fontSize: 0.75, color: '#a3a3a3', padding: '0 2px' }}>{t.year} · {t.genre || '—'}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
