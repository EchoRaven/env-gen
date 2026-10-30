import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import { CaretDown } from '../icons.jsx'

// "Genres" dropdown on the Shows / Movies landings, backed by GET /api/genres?kind=.
export default function GenresMenu({ kind }) {
  const { profileId } = useSession()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const { data } = useAsync(() => api.genres({ kind }), [kind, profileId])
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const items = data?.items || []
  return (
    <div className="genres-menu" ref={ref}>
      <button className="genres-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        Genres <CaretDown size={12} />
      </button>
      {open && (
        <div className="genres-drop" style={{ gridTemplateRows: `repeat(${Math.max(1, Math.ceil(items.length / 3))}, auto)` }}>
          {items.length === 0 && <span className="muted">No genres</span>}
          {items.map((g) => (
            <Link key={g.id} to={`/browse/genre/${g.id}?kind=${kind}`} onClick={() => setOpen(false)}>{g.name}</Link>
          ))}
        </div>
      )}
    </div>
  )
}
