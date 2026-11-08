import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Icon from './Icon.jsx'
import { useAuth } from '../context/AuthContext.jsx'

export default function GenreMenu({ label = 'Genres' }) {
  const { api } = useAuth()
  const [open, setOpen] = useState(false)
  const [genres, setGenres] = useState([])
  const [error, setError] = useState('')
  const wrap = useRef(null)

  useEffect(() => {
    if (!open || genres.length) return
    let cancelled = false
    api.get('/api/genres').then((result) => {
      if (!cancelled) setGenres(result.items || [])
    }).catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [open, genres.length, api])

  useEffect(() => {
    function outside(event) { if (wrap.current && !wrap.current.contains(event.target)) setOpen(false) }
    document.addEventListener('mousedown', outside)
    return () => document.removeEventListener('mousedown', outside)
  }, [])

  return (
    <div className="category-bar">
      <div className="genre-menu-wrap" ref={wrap}>
        <button type="button" className="genre-menu-button" onClick={() => setOpen((value) => !value)}>
          {label} <Icon name="chevron-down" size={15} />
        </button>
        {open && (
          <div className="dropdown genre-menu">
            <div className="dropdown-heading">Browse by genre</div>
            {error && <div className="empty-inline">{error}</div>}
            <div className="genre-menu-grid">
              {genres.map((genre) => (
                <Link key={genre.id} to={`/browse/genre/${genre.id}`} onClick={() => setOpen(false)}>{genre.name}<small>{genre.title_count}</small></Link>
              ))}
            </div>
            {!genres.length && !error && <div className="empty-inline">Loading genres…</div>}
          </div>
        )}
      </div>
    </div>
  )
}
