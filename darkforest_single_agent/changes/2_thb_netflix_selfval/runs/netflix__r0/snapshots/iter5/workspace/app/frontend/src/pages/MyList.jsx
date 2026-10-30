import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import TitleCard from '../components/TitleCard.jsx'

export default function MyList() {
  const { profileId, listVersion, inList } = useSession()
  const { data, loading, error } = useAsync(() => api.myList(), [profileId, listVersion])
  const items = (data?.items || []).filter((t) => inList(t))
  return (
    <div className="grid-page">
      <h1 className="page-title">My List</h1>
      {loading && !data && <div className="spinner" />}
      {error && <p className="row-empty">Couldn’t load My List: {error.message}</p>}
      {data && items.length === 0 && (
        <div className="empty-state">
          <h3>Your list is empty</h3>
          <p>Add shows and movies with the <b>+</b> button and they’ll show up here — only for this profile.</p>
          <div className="empty-actions"><Link className="btn-white" to="/browse">Find something to watch</Link></div>
        </div>
      )}
      <div className="title-grid">{items.map((t) => <TitleCard key={t.id} t={t} />)}</div>
    </div>
  )
}
