import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import TitleCard from '../components/TitleCard.jsx'
import { useTitleOverlay } from '../components/useTitleOverlay.js'

export default function MyListPage() {
  const { api } = useAuth()
  const { openTitle } = useTitleOverlay()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadList = useCallback(() => {
    setLoading(true)
    api.get('/api/my-list').then((result) => {
      setItems(result.items || [])
      setError('')
    }).catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [api])

  useEffect(() => {
    loadList()
    const refresh = () => loadList()
    window.addEventListener('netflix:mylist', refresh)
    return () => window.removeEventListener('netflix:mylist', refresh)
  }, [loadList])

  return (
    <PageShell className="browse-app list-page">
      <div className="browse-main">
        <div className="list-heading">
          <div>
            <h1>My List</h1>
          </div>
        </div>
        {loading && <div className="page-loading">Loading My List…</div>}
        {error && <div className="page-error">{error}</div>}
        {!loading && !error && (
          items.length ? (
            <div className="poster-grid">{items.map((item) => <TitleCard key={item.id} item={item} onOpen={openTitle} />)}</div>
          ) : (
            <div className="poster-grid-empty">
              <h3>Your list is empty</h3>
              <p>Add films and series with the + button and they will appear here for this profile only.</p>
            </div>
          )
        )}
      </div>
    </PageShell>
  )
}
