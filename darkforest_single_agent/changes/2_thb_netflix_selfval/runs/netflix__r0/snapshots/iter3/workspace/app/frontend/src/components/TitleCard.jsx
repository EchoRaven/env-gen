import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useSession } from '../session.jsx'
import { Icon } from '../icons.jsx'
import { genreNames, isNew, lengthLabel } from '../format.js'

export function Badges({ t, ribbon = true }) {
  return (
    <>
      {t.top10_rank && <span className="top10-badge" title={`#${t.top10_rank} in ${t.kind === 'series' ? 'TV Shows' : 'Movies'} Today`}><small>TOP</small>10</span>}
      {ribbon && isNew(t) && <span className="ribbon">Recently Added</span>}
    </>
  )
}

export function RatingButtons({ title, compact = false }) {
  const { ratingOf, rateTitle } = useSession()
  const r = ratingOf(title)
  const opts = [[-1, 'thumbsDown', 'Not for me'], [1, 'thumbsUp', 'I like this'], [2, 'thumbsUpTwo', 'Love this!']]
  return (
    <div className={`rate-pop ${compact ? 'compact' : ''}`}>
      {opts.map(([v, icon, label]) => (
        <button key={v} className={`rate-opt ${r === v ? 'on' : ''}`} aria-label={label}
          aria-pressed={r === v} onClick={(e) => { e.stopPropagation(); rateTitle(title, v) }}>
          <Icon name={icon} size={22} />
          <span className="tip">{r === v ? 'Rated' : label}</span>
        </button>
      ))}
    </div>
  )
}

export function ThumbButton({ title, size = 'md' }) {
  const { ratingOf } = useSession()
  const [open, setOpen] = useState(false)
  const r = ratingOf(title)
  const icon = r === -1 ? 'thumbsDown' : r === 2 ? 'thumbsUpTwo' : 'thumbsUp'
  return (
    <div className={`thumb-wrap ${open ? 'open' : ''}`} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button className={`circle-btn ${size} ${r ? 'rated' : ''}`} aria-label="Rate this title"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}>
        <Icon name={icon} size={size === 'lg' ? 24 : 20} />
      </button>
      {open && <RatingButtons title={title} />}
    </div>
  )
}

export function ListButton({ title, size = 'md' }) {
  const { inList, toggleList } = useSession()
  const on = inList(title)
  return (
    <button className={`circle-btn ${size}`} aria-label={on ? 'Remove from My List' : 'Add to My List'}
      title={on ? 'Remove from My List' : 'Add to My List'}
      onClick={(e) => { e.stopPropagation(); toggleList(title) }}>
      <Icon name={on ? 'check' : 'plus'} size={size === 'lg' ? 24 : 20} />
    </button>
  )
}

function Preview({ t, rect, onClose }) {
  const navigate = useNavigate()
  const { openTitle } = useSession()
  const [muted, setMuted] = useState(true)
  const [playing, setPlaying] = useState(false)
  const vid = useRef(null)
  const width = Math.max(rect.width * 1.5, 340)
  let left = rect.left + window.scrollX + rect.width / 2 - width / 2
  left = Math.max(window.scrollX + 16, Math.min(left, window.scrollX + document.documentElement.clientWidth - width - 16))
  const top = rect.top + window.scrollY - rect.height * 0.55
  useEffect(() => {
    const id = setTimeout(() => setPlaying(true), 700)
    return () => clearTimeout(id)
  }, [])
  const genres = genreNames(t)
  return createPortal(
    <div className="preview" style={{ left, top, width }} onMouseLeave={onClose}>
      <div className="preview-media" onClick={() => { onClose(); openTitle(t.id) }}>
        <img src={t.backdrop} alt="" />
        {playing && t.video_url && (
          <video ref={vid} src={t.video_url} autoPlay muted={muted} loop playsInline
            onPlaying={(e) => e.currentTarget.classList.add('on')} />
        )}
        <div className="preview-title">{t.name}</div>
        {playing && (
          <button className="mute-btn sm" aria-label={muted ? 'Unmute' : 'Mute'}
            onClick={(e) => { e.stopPropagation(); setMuted((m) => !m) }}>
            <Icon name={muted ? 'volumeOff' : 'volumeHigh'} size={18} />
          </button>
        )}
      </div>
      <div className="preview-info">
        <div className="preview-actions">
          <button className="circle-btn md white" aria-label={`Play ${t.name}`} onClick={() => { onClose(); navigate(`/watch/${t.id}`) }}>
            <Icon name="play" size={20} />
          </button>
          <ListButton title={t} />
          <ThumbButton title={t} />
          <button className="circle-btn md push-right" aria-label="More info" title="Episodes & info"
            onClick={() => { onClose(); openTitle(t.id) }}>
            <Icon name="chevronDown" size={22} />
          </button>
        </div>
        <div className="meta-line">
          <span className="maturity">{t.maturity_rating}</span>
          <span>{lengthLabel(t)}</span>
          <span className="hd">HD</span>
        </div>
        {genres.length > 0 && (
          <div className="tag-line">{genres.map((g, i) => <span key={g}>{i > 0 && <i className="dot" />}{g}</span>)}</div>
        )}
      </div>
    </div>,
    document.body
  )
}

export default function TitleCard({ t, progress, variant = 'backdrop' }) {
  const { openTitle } = useSession()
  const [rect, setRect] = useState(null)
  const ref = useRef(null)
  const timer = useRef(null)

  const enter = () => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      if (ref.current && window.matchMedia('(hover: hover)').matches) setRect(ref.current.getBoundingClientRect())
    }, 450)
  }
  const leave = () => clearTimeout(timer.current)
  useEffect(() => () => clearTimeout(timer.current), [])
  useEffect(() => {
    if (!rect) return
    const close = () => setRect(null)
    window.addEventListener('scroll', close, { passive: true })
    return () => window.removeEventListener('scroll', close)
  }, [rect])

  return (
    <>
      <button ref={ref} className={`title-card ${variant}`} onMouseEnter={enter} onMouseLeave={leave}
        onClick={() => { clearTimeout(timer.current); openTitle(t.id) }} aria-label={t.name}>
        <img src={variant === 'poster' ? t.poster : t.backdrop} alt="" loading="lazy" />
        {variant !== 'poster' && <span className="card-title">{t.name}</span>}
        <Badges t={t} ribbon={progress == null} />
        {progress != null && (
          <span className="card-progress"><span style={{ width: `${Math.min(100, progress * 100)}%` }} /></span>
        )}
      </button>
      {rect && <Preview t={t} rect={rect} onClose={() => setRect(null)} />}
    </>
  )
}
