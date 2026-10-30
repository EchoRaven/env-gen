import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from '../session.jsx'
import { Icon } from '../icons.jsx'
import TitleCard from './TitleCard.jsx'

// A horizontally-paged rail with chevron controls and Netflix-style page indicators.
export default function Row({ title, items, loading, error, size = 'md', ranked = false, emptyText, badge, children }) {
  const track = useRef(null)
  const [page, setPage] = useState(0)
  const [pages, setPages] = useState(1)
  const { openTitle } = useSession()

  const measure = useCallback(() => {
    const el = track.current
    if (!el) return
    const n = Math.max(1, Math.ceil((el.scrollWidth - 4) / el.clientWidth))
    setPages(n)
    setPage(Math.min(n - 1, Math.round(el.scrollLeft / el.clientWidth)))
  }, [])

  useEffect(() => {
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure, items])

  const go = (dir) => {
    const el = track.current
    if (!el) return
    el.scrollBy({ left: dir * (el.clientWidth - 8), behavior: 'smooth' })
  }

  if (!loading && !error && items && items.length === 0 && !emptyText) return null

  return (
    <section className={`row row-${size} ${ranked ? 'row-ranked' : ''}`}>
      <div className="row-head">
        <h2 className="row-title">{title}{badge}</h2>
        {pages > 1 && (
          <div className="row-pages" aria-hidden="true">
            {Array.from({ length: pages }).map((_, i) => <i key={i} className={i === page ? 'on' : ''} />)}
          </div>
        )}
      </div>
      {loading && <div className="row-track skeleton-track">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="card-skel" />)}</div>}
      {error && <p className="row-empty">Couldn’t load this row: {error.message}</p>}
      {!loading && !error && items && items.length === 0 && <p className="row-empty">{emptyText}</p>}
      {!loading && !error && items && items.length > 0 && (
        <div className="row-viewport">
          {page > 0 && (
            <button className="row-arrow left" aria-label={`Scroll ${title} left`} onClick={() => go(-1)}>
              <Icon name="chevronLeft" size={36} />
            </button>
          )}
          <div className="row-track" ref={track} onScroll={measure}>
            {children
              ? children
              : items.map((it, i) => ranked ? (
                <button key={it.id} className="ranked-card" onClick={() => openTitle(it.id)} aria-label={`${i + 1}. ${it.name}`}>
                  <span className="rank-num">{it.top10_rank || i + 1}</span>
                  <img src={it.poster} alt="" loading="lazy" />
                  {it.year === '2026' && <span className="ribbon">Recently Added</span>}
                </button>
              ) : (
                <TitleCard key={it.id} t={it}
                  progress={it.progress_seconds != null && it.duration ? it.progress_seconds / it.duration : null} />
              ))}
          </div>
          {page < pages - 1 && (
            <button className="row-arrow right" aria-label={`Scroll ${title} right`} onClick={() => go(1)}>
              <Icon name="chevronRight" size={36} />
            </button>
          )}
        </div>
      )}
    </section>
  )
}
