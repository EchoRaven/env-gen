import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import EmptyState from '../components/EmptyState'
import Spinner from '../components/Spinner'
import TitleCard from '../components/TitleCard'
import TitleModal from '../components/TitleModal'
import { useAuth } from '../context/AuthContext'

export default function MyListPage() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedTitle, setSelectedTitle] = useState(null)
  const { profile } = useAuth()

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.get('/api/my-list')
      setItems(data.items || [])
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [profile?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="list-page">
      <div className="list-header">
        <span className="sr-only">{profile?.name}’s List</span>
        <h1>My List</h1>
        <p>{items.length ? `${items.length} saved ${items.length === 1 ? 'title' : 'titles'} — private to this profile.` : 'Everything you save will live here, private to this profile.'}</p>
        <div className="list-header-actions">
          <Link className="btn btn-light btn-small" to="/browse">Browse the catalog</Link>
          <Link className="btn btn-outline btn-small" to="/new">See what’s new</Link>
        </div>
      </div>
      <div className="page-content list-content">
        {loading ? <Spinner label="Loading My List…" /> : items.length ? (
          <div className="poster-grid">
            {items.map((item) => (
              <TitleCard key={item.id} title={item} onOpen={setSelectedTitle} onChanged={load} />
            ))}
          </div>
        ) : (
          <EmptyState
            title="Your list is empty"
            message="Add films and series with the + button. My List is separately maintained for every profile."
            actionLabel="Find something to watch"
            actionTo="/browse"
          />
        )}
      </div>
      {selectedTitle ? <TitleModal titleId={selectedTitle.id} initialTitle={selectedTitle} onClose={() => setSelectedTitle(null)} onChanged={load} /> : null}
    </div>
  )
}
