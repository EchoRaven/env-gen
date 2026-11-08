import React, { useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, assetUrl } from '../api'
import Avatar from './Avatar'
import Icon from './Icon'

export function PosterCard({ title, onOpen, onChanged, rank = null, large = false }) {
  const navigate = useNavigate()
  const [busy, setBusy] = React.useState(false)
  const [inList, setInList] = React.useState(Boolean(title.is_in_my_list))
  const [rating, setRating] = React.useState(title.my_rating ?? null)
  const [imgOk, setImgOk] = React.useState(true)
  const [hover, setHover] = React.useState(false)
  const hoverTimer = useRef(null)

  React.useEffect(() => {
    setInList(Boolean(title.is_in_my_list))
    setRating(title.my_rating ?? null)
  }, [title.is_in_my_list, title.my_rating])

  const hoverIn = () => {
    clearTimeout(hoverTimer.current)
    hoverTimer.current = setTimeout(() => setHover(true), 380)
  }
  const hoverOut = () => {
    clearTimeout(hoverTimer.current)
    setHover(false)
  }

  const play = (event) => {
    event.stopPropagation()
    navigate(`/watch/${title.id}`)
  }

  const toggleList = async (event) => {
    event.stopPropagation()
    if (busy) return
    setBusy(true)
    try {
      if (inList) await api(`/api/my-list/${title.id}`, { method: 'DELETE' })
      else await api('/api/my-list', { method: 'POST', body: { title_id: title.id } })
      setInList(value => !value)
      onChanged?.()
    } catch (error) {
      console.error(error)
    } finally { setBusy(false) }
  }

  const rate = async (event) => {
    event.stopPropagation()
    try {
      const result = await api(`/api/titles/${title.id}/rating`, { method: 'POST', body: { value: 1 } })
      setRating(result.value)
      onChanged?.()
    } catch (error) { console.error(error) }
  }

  const expand = (event) => {
    event.stopPropagation()
    onOpen?.(title.id)
  }

  return (
    <div
      className={`poster-card ${large ? 'large' : ''}`}
      onMouseEnter={hoverIn}
      onMouseLeave={hoverOut}
      onClick={() => onOpen?.(title.id)}
      role="button"
      tabIndex={0}
      onKeyDown={event => { if (event.key === 'Enter') onOpen?.(title.id) }}
      aria-label={`${title.name}, ${title.year}`}
    >
      {rank && <span className={`rank-number ${rank > 9 ? 'wide' : ''}`}>{rank}</span>}
      <div className="poster-art">
        <img
          src={imgOk ? assetUrl(rank ? title.poster : (title.backdrop || title.poster)) : assetUrl(title.poster)}
          alt={title.name}
          loading="lazy"
          onError={() => setImgOk(false)}
        />
        <div className="poster-shade" />
        {!rank && <div className="card-title-overlay">{title.name}</div>}
        {title.progress_seconds > 0 && (
          <div className="card-progress"><span style={{ width: `${Math.min(100, title.progress_seconds / Math.max(1, title.duration) * 100)}%` }} /></div>
        )}
      </div>
      {hover && (
        <div className="card-hover" onClick={event => event.stopPropagation()}>
          <div className="card-hover-art">
            <img src={assetUrl(title.backdrop || title.poster)} alt="" />
            <div className="card-hover-gradient" />
            <div className="card-hover-title">{title.name}</div>
          </div>
          <div className="card-hover-controls">
            <button className="round-button light" onClick={play} aria-label={`Play ${title.name}`}><Icon name="play" size={18} /></button>
            <button className={`round-button ${inList ? 'selected' : ''}`} onClick={toggleList} disabled={busy} aria-label={inList ? 'Remove from My List' : 'Add to My List'}>
              <Icon name={inList ? 'check' : 'plus'} size={18} />
            </button>
            <button className={`round-button ${rating === 1 ? 'selected' : ''}`} onClick={rate} aria-label="Thumbs up">
              <Icon name="thumbs-up" size={17} />
            </button>
            <button className="round-button push" onClick={expand} aria-label={`More info about ${title.name}`}>
              <Icon name="chevron-down" size={18} />
            </button>
          </div>
          <div className="card-hover-meta">
            <span className="match">{Math.max(72, Math.round((title.rating || 6) * 10))}% Match</span>
            <span className="maturity">{title.maturity_rating}</span>
            <span>{title.kind === 'series' ? `${title.seasons || 1} Season${title.seasons === 1 ? '' : 's'}` : title.duration_label}</span>
          </div>
          <div className="card-tags">{(title.genres || []).slice(0, 3).map(genre => <span key={genre}>{genre}</span>)}</div>
        </div>
      )}
    </div>
  )
}

export default function Row({ title, titles = [], onOpen, onChanged, kind = 'standard', ranked = false }) {
  const railRef = useRef(null)
  if (!titles?.length) {
    return (
      <section className="rail empty-rail">
        <div className="rail-heading"><h2>{title}</h2></div>
        <div className="rail-empty-state">Nothing to show here yet.</div>
      </section>
    )
  }
  const scroll = (direction) => {
    railRef.current?.scrollBy({ left: direction * Math.max(500, railRef.current.clientWidth * 0.8), behavior: 'smooth' })
  }
  return (
    <section className={`rail ${kind}`}>
      <div className="rail-heading">
        <h2>{title}</h2>
      </div>
      <div className="rail-viewport">
        <button className="rail-arrow left" onClick={() => scroll(-1)} aria-label={`Scroll ${title} left`}>
          <Icon name="chevron-left" size={30} />
        </button>
        <div className="rail-track" ref={railRef}>
          {titles.map((item, index) => (
            <PosterCard
              key={`${item.id}-${index}`}
              title={item}
              onOpen={onOpen}
              onChanged={onChanged}
              rank={ranked ? (item.top10_rank || index + 1) : null}
              large={ranked}
            />
          ))}
        </div>
        <button className="rail-arrow right" onClick={() => scroll(1)} aria-label={`Scroll ${title} right`}>
          <Icon name="chevron-right" size={30} />
        </button>
      </div>
    </section>
  )
}
