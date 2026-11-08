import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from './Icon'

export function LoadingPage({ label = 'Loading…' }) {
  return <div className="page-loading"><span className="spinner" /> {label}</div>
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="page-error">
      <Icon name="info" size={34} />
      <h2>We couldn&apos;t load this page</h2>
      <p>{message || 'Please try again.'}</p>
      {onRetry && <button className="btn btn-secondary" onClick={onRetry}>Try Again</button>}
    </div>
  )
}

export function EmptyState({ icon = 'info', title, message, actionLabel, onAction }) {
  return (
    <div className="page-empty">
      <span className="empty-icon"><Icon name={icon} size={46} /></span>
      <h2>{title}</h2>
      {message && <p>{message}</p>}
      {actionLabel && <button className="btn btn-secondary" onClick={onAction}>{actionLabel}</button>}
    </div>
  )
}

export function GenreDropdown({ genres, selected, kindLabel = '' }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)

  useEffect(() => {
    const close = event => { if (wrapRef.current && !wrapRef.current.contains(event.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  return (
    <div className="genre-dropdown-wrap" ref={wrapRef}>
      <button className="genre-dropdown-button" onClick={() => setOpen(value => !value)} aria-expanded={open}>
        Genres <Icon name="chevron-down" size={18} />
      </button>
      {open && (
        <div className="genre-dropdown">
          <button onClick={() => { setOpen(false); navigate(kindLabel === 'Movies' ? '/movies' : '/shows') }}>All {kindLabel || 'Titles'}</button>
          {genres.map(genre => (
            <button key={genre.id} onClick={() => { setOpen(false); navigate(`/browse/genre/${genre.id}`) }}>
              {genre.name}<span>{genre.title_count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function PosterGrid({ titles, onOpen, emptyTitle = 'Nothing here yet', emptyMessage }) {
  if (!titles?.length) return <EmptyState title={emptyTitle} message={emptyMessage} />
  return (
    <div className="poster-grid">
      {titles.map(item => (
        <button className="grid-poster" key={item.id} onClick={() => onOpen?.(item.id)}>
          <img src={`/${String(item.poster).replace(/^\/+/, '')}`} alt={item.name} loading="lazy" />
          <span className="grid-poster-overlay"><strong>{item.name}</strong><span>{item.year} · {item.maturity_rating}</span></span>
        </button>
      ))}
    </div>
  )
}
