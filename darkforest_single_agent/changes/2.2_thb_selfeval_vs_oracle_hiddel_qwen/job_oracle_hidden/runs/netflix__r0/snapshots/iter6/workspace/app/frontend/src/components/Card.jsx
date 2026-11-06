import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from './Icon'
import { mediaUrl, matchPct, clamp } from '../lib/util'
import { useApp } from '../state/AppContext'
import { openTitleModal } from '../lib/modalStore'
import RateDialog from './RateDialog'

export default function Card({ title, rank }) {
  const nav = useNavigate()
  const { myListIds, addToList, removeFromList } = useApp()
  const ref = useRef(null)
  const hideTimer = useRef(null)
  const showTimer = useRef(null)
  const [hover, setHover] = useState(false)
  const [pos, setPos] = useState(null)
  const [rateOpen, setRateOpen] = useState(false)
  const inList = myListIds.has(title.id)
  const match = matchPct(title.rating)

  const show = () => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const w = 340
    const left = clamp(r.left + r.width / 2 - w / 2, 8, Math.max(8, window.innerWidth - w - 8))
    const top = clamp(r.bottom - 24, 76, Math.max(76, window.innerHeight - 330))
    setPos({ left, top })
    setHover(true)
  }
  const scheduleShow = () => {
    cancelHide()
    showTimer.current = setTimeout(show, 260)
  }
  const scheduleHide = () => {
    if (showTimer.current) clearTimeout(showTimer.current)
    hideTimer.current = setTimeout(() => setHover(false), 180)
  }
  const cancelHide = () => { if (hideTimer.current) clearTimeout(hideTimer.current) }
  useEffect(() => () => { cancelHide(); if (showTimer.current) clearTimeout(showTimer.current) }, [])

  const toggleList = (e) => {
    e.stopPropagation()
    if (inList) removeFromList(title.id).catch(() => {})
    else addToList(title.id).catch(() => {})
  }

  const play = (e) => {
    e.stopPropagation()
    nav(`/watch/${title.id}`)
  }

  return (
    <>
      <div
        ref={ref}
        className="card"
        onMouseEnter={scheduleShow}
        onMouseLeave={scheduleHide}
        onClick={() => openTitleModal(title.id)}
      >
        <img className="card-poster" src={mediaUrl(title.poster)} alt={title.name} loading="lazy" />
        <div className="card-hoverbar">
          <button className="mini-btn" aria-label={`Play ${title.name}`} onClick={play}><Icon name="play" size={15} /></button>
          <button className={`mini-btn ${inList ? 'active' : ''}`} aria-label="Toggle My List" onClick={toggleList}>
            <Icon name={inList ? 'check' : 'plus'} size={15} />
          </button>
          <button className="mini-btn" aria-label="Rate title" onClick={(e) => { e.stopPropagation(); setRateOpen(true) }}>
            <Icon name="thumbs_up" size={15} />
          </button>
          <button className="mini-btn" aria-label="More info" onClick={(e) => { e.stopPropagation(); openTitleModal(title.id) }}>
            <Icon name="chevron_down" size={15} />
          </button>
        </div>
      </div>
      {hover && pos && (
        <div className="hover-card" style={{ left: pos.left, top: pos.top }} onMouseEnter={cancelHide} onMouseLeave={scheduleHide}>
          <img className="hc-img" src={mediaUrl(title.backdrop || title.poster)} alt="" />
          <div className="hc-body">
            <div className="hc-actions">
              <button className="mini-btn" aria-label="Play" onClick={play}><Icon name="play" size={15} /></button>
              <button className={`mini-btn ${inList ? 'active' : ''}`} aria-label="Toggle My List" onClick={toggleList}>
                <Icon name={inList ? 'check' : 'plus'} size={15} />
              </button>
              <button className="mini-btn" aria-label="Rate" onClick={() => setRateOpen(true)}><Icon name="thumbs_up" size={15} /></button>
              <button className="mini-btn" aria-label="More info" onClick={() => openTitleModal(title.id)}><Icon name="chevron_down" size={15} /></button>
              <div style={{ flex: 1 }} />
              <span className="maturity-badge">{title.maturity_rating || '—'}</span>
            </div>
            <div className="hc-meta">
              {match != null && <span className="match">{match}% Match</span>}
              <span style={{ color: '#a3a3a3' }}>{title.year}</span>
            </div>
            <div className="hc-tags">
              {(title.genres && title.genres.length ? title.genres : [title.genre]).filter(Boolean).slice(0, 3).map((g, i) => (
                <span key={i}>{g}</span>
              ))}
            </div>
          </div>
        </div>
      )}
      {rateOpen && <RateDialog titleId={title.id} titleName={title.name} onClose={() => setRateOpen(false)} />}
    </>
  )
}
