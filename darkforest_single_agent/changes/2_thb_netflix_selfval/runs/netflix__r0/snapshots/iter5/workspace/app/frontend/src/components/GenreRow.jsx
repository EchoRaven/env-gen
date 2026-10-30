import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import Row from './Row.jsx'

// A rail backed by GET /api/genres/{id}/titles; the heading links to the genre page.
export default function GenreRow({ genre, kind, label }) {
  const { profileId } = useSession()
  const s = useAsync(() => (genre ? api.genreTitles(genre.id, { kind }) : Promise.resolve({ items: [] })), [genre && genre.id, kind, profileId])
  if (!genre) return null
  const to = `/browse/genre/${genre.id}${kind ? `?kind=${kind}` : ''}`
  return (
    <Row title={<Link to={to} className="row-link">{label || genre.name}<span className="explore">Explore All ›</span></Link>}
      items={s.data?.items} loading={s.loading} error={s.error} />
  )
}
