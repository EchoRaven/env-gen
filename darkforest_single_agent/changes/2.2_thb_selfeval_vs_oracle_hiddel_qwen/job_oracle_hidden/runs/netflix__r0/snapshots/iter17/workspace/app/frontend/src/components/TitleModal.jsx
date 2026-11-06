import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from './Icon'
import { api } from '../lib/api'
import { mediaUrl, fmtDuration, matchPct } from '../lib/util'
import { useApp } from '../state/AppContext'
import RateDialog from './RateDialog'

export default function TitleModal({ titleId, onClose }) {
  const nav = useNavigate()
  const { myListIds, addToList, removeFromList, ratings } = useApp()
  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState(null)
  const [season, setSeason] = useState(null)
  const [error, setError] = useState(null)
  const [rateOpen, setRateOpen] = useState(false)

  useEffect(() => {
    let alive = true
    setTitle(null); setEpisodes(null); setError(null)
    api(`/api/titles/${titleId}`)
      .then(async (t) => {
        if (!alive) return
        setTitle(t)
        if (t.kind === 'series') {
          const ep = await api(`/api/titles/${titleId}/episodes`)
          if (!alive) return
          setEpisodes(ep || [])
        }
      })
      .catch((e) => alive && setError(e.message))
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => { alive = false; window.removeEventListener('keydown', onKey); document.body.style.overflow = '' }
  }, [titleId, onClose])

  const inList = title ? myListIds.has(title.id) : false
  const rating = title ? ratings[title.id] : undefined

  const seasons = useMemo(() => [...new Set((episodes || []).map((e) => e.season))].sort((a, b) => a - b), [episodes])
  const seasonEps = useMemo(
    () => (episodes ? episodes.filter((e) => e.season === season) : []),
    [episodes, season],
  )

  // default to first season once episodes arrive
  useEffect(() => {
    if (episodes && episodes.length && seasons.length && season == null) setSeason(seasons[0])
  }, [episodes, seasons, season])

  if (error) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal" style={{ minHeight: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={(e) => e.stopPropagation()}>
          <div style={{ color: '#e5e5e5', fontSize: 1.05, padding: 40 }}>
            Title not found. <button className="btn btn-red" style={{ padding: '8px 18px', fontSize: '0.95rem' }} onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    )
  }

  if (!title) return null
  const match = matchPct(title.rating)
  const seasonCount = seasons.length

  const toggleList = () => {
    if (inList) removeFromList(title.id).catch(() => {})
    else addToList(title.id).catch(() => {})
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" aria-label="Close" onClick={onClose}><Icon name="close" size={20} /></button>
        <div className="modal-backdrop">
          <img src={mediaUrl(title.backdrop || title.poster)} alt="" />
        </div>
        <div className="modal-body">
          <h1 className="modal-title">{title.name}</h1>
          <div className="modal-meta">
            {match != null && <span className="match">{match}% Match</span>}
            <span style={{ color: '#cfcfcf' }}>{title.year}</span>
            <span className="hd-badge">HD</span>
            {seasonCount > 0 && <span style={{ color: '#cfcfcf' }}>{seasonCount} {seasonCount === 1 ? 'Season' : 'Seasons'}</span>}
            {title.top10_rank && (
              <span style={{ color: '#e50914', fontWeight: 600 }}>
                #{title.top10_rank} in {title.kind === 'series' ? 'TV Shows' : 'Movies'} Today
              </span>
            )}
          </div>
          <div className="modal-actions">
            <button className="btn btn-play" onClick={() => nav(`/watch/${title.id}`)}>
              <Icon name="play" size={24} /> Play
            </button>
            <button className={`round-btn ${inList ? 'active' : ''}`} aria-label="Toggle My List" title={inList ? 'Remove from My List' : 'Add to My List'} onClick={toggleList}>
              <Icon name={inList ? 'check' : 'plus'} size={20} />
            </button>
            <button className={`round-btn ${rating ? 'active' : ''}`} aria-label="Rate title" title="Rate this title" onClick={() => setRateOpen(true)}>
              <Icon name="thumbs_up" size={20} />
            </button>
          </div>
          <div className="modal-meta" style={{ margin: 0 }}>
            <span className="maturity-badge">{title.maturity_rating || '—'}</span>
            {title.rating != null && <span style={{ color: '#cfcfcf' }}>Rated {title.rating} / 10</span>}
          </div>
          {title.synopsis && <p className="modal-synopsis" style={{ marginTop: 14 }}>{title.synopsis}</p>}
          {title.genres && title.genres.length > 0 && (
            <div className="modal-genres">
              <strong style={{ color: '#707070', fontWeight: 500 }}>Genres: </strong>
              {title.genres.map((g) => <span key={g}>{g}</span>)}
            </div>
          )}

          {title.kind === 'series' && (
            <div>
              <div className="episodes-header">
                <h2>Episodes</h2>
                <span className="ep-count">{seasonCount} {seasonCount === 1 ? 'Season' : 'Seasons'}</span>
                <select
                  className="season-select"
                  value={season ?? ''}
                  onChange={(e) => setSeason(parseInt(e.target.value, 10))}
                  aria-label="Select season"
                >
                  {seasons.map((s) => (
                    <option key={s} value={s}>Season {s}</option>
                  ))}
                </select>
              </div>
              {episodes === null && <div className="rail-empty">Loading episodes…</div>}
              {episodes && seasonEps.length === 0 && <div className="rail-empty">No episodes in this season.</div>}
              {seasonEps.map((ep) => (
                <div key={ep.id} className="ep-row" onClick={() => nav(`/watch/${title.id}?episode=${ep.id}`)}>
                  <div className="ep-thumb">
                    <img src={mediaUrl(ep.thumbnail || title.backdrop || title.poster)} alt="" loading="lazy" />
                    <span className="ep-play"><Icon name="play" size={14} /></span>
                  </div>
                  <div className="ep-num">{ep.number}</div>
                  <div className="ep-info">
                    <h3>{ep.name}</h3>
                    <p>{ep.synopsis || '—'}</p>
                  </div>
                  <div className="ep-dur">{fmtDuration(ep.duration)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {rateOpen && <RateDialog titleId={title.id} titleName={title.name} initial={rating} onClose={() => setRateOpen(false)} />}
    </div>
  )
}
