import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, assetUrl } from '../api'
import { LoadingPage, ErrorState, EmptyState } from '../components/PageUtilities'
import { useOpenTitle } from '../hooks'
import Icon from '../components/Icon'

export default function MyList() {
  const [titles, setTitles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)
  const [removing, setRemoving] = useState(null)
  const openTitle = useOpenTitle()
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    api('/api/my-list')
      .then(setTitles).catch(err => setError(err.message)).finally(() => setLoading(false))
  }, [nonce])

  const remove = async (title) => {
    setRemoving(title.id)
    try {
      await api(`/api/my-list/${title.my_list_id || title.id}`, { method: 'DELETE' })
      setTitles(list => list.filter(item => item.id !== title.id))
    } catch (err) { setError(err.message) }
    finally { setRemoving(null) }
  }

  return (
    <div className="simple-catalog-page my-list-page">
      <div className="simple-page-heading"><h1>My List</h1><p>Saved to your profile, {titles.length ? `${titles.length} title${titles.length === 1 ? '' : 's'}` : 'ready when you are'}.</p></div>
      {loading && <LoadingPage label="Loading My List…" />}
      {!loading && error && <ErrorState message={error} onRetry={() => setNonce(v => v + 1)} />}
      {!loading && !error && titles.length === 0 && (
        <EmptyState
          icon="plus"
          title="Your list is empty"
          message="Add movies and shows with the + button and they will appear here for this profile only."
          actionLabel="Find something to watch"
          onAction={() => navigate('/browse')}
        />
      )}
      {!loading && !error && titles.length > 0 && (
        <div className="grid-wrap">
          <div className="poster-grid">
            {titles.map(item => (
              <div className="grid-poster-wrap" key={item.id}>
                <button className="grid-poster" onClick={() => openTitle(item.id)}>
                  <img src={assetUrl(item.poster)} alt={item.name} loading="lazy" />
                  <span className="grid-poster-overlay"><strong>{item.name}</strong><span>{item.year} · {item.maturity_rating}</span></span>
                </button>
                <button className="remove-list-button" onClick={() => remove(item)} disabled={removing === item.id} aria-label={`Remove ${item.name} from My List`}>
                  <Icon name="close" size={16} /> {removing === item.id ? 'Removing…' : 'Remove'}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
