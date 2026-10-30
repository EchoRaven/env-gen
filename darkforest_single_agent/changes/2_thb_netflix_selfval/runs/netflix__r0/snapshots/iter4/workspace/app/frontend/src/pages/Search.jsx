import { useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import TitleCard from '../components/TitleCard.jsx'

export default function Search() {
  const [params] = useSearchParams()
  const q = params.get('q') || ''
  const { profileId } = useSession()
  const { data, loading, error } = useAsync(() => api.search(q), [q, profileId])
  const items = data?.items || []
  return (
    <div className="grid-page">
      {q && <p className="search-label">Results for <b>“{q}”</b>{data ? ` · ${items.length} title${items.length === 1 ? '' : 's'}` : ''}</p>}
      {!q && <p className="search-label">Type in the search box to find titles by name, genre or plot.</p>}
      {loading && <div className="spinner" />}
      {error && <p className="row-empty">Search failed: {error.message}</p>}
      {data && q && items.length === 0 && (
        <div className="empty-state left">
          <p>Your search for “{q}” did not have any matches.</p>
          <p className="muted">Suggestions: try different keywords, or a genre such as Comedy, Drama or Animation.</p>
        </div>
      )}
      <div className="title-grid">{items.map((t) => <TitleCard key={t.id} t={t} />)}</div>
    </div>
  )
}
