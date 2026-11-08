import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import Icon from './Icon.jsx'
import { formatRuntime } from './HeroBillboard.jsx'

export default function TitleCard({ item, onOpen, top10Rank, showProgress = false, noPreview = false, className = '' }) {
  const { api } = useAuth()
  const navigate = useNavigate()
  const anchorRef = useRef(null)
  const previewRef = useRef(null)
  const openTimer = useRef(null)
  const closeTimer = useRef(null)
  const [preview, setPreview] = useState(null)
  const [inList, setInList] = useState(Boolean(item.in_my_list))
  const [listId, setListId] = useState(item.my_list_id || null)
  const [userRating, setUserRating] = useState(item.user_rating ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { setInList(Boolean(item.in_my_list)); setListId(item.my_list_id || null); setUserRating(item.user_rating ?? null) },
    [item.id, item.in_my_list, item.my_list_id, item.user_rating])

  useEffect(() => () => {
    clearTimeout(openTimer.current)
    clearTimeout(closeTimer.current)
  }, [])

  function positionPreview() {
    if (!anchorRef.current) return
    const rect = anchorRef.current.getBoundingClientRect()
    const width = Math.min(Math.max(rect.width * 1.42, 260), 390)
    let left = rect.left + rect.width / 2 - width / 2
    left = Math.max(12, Math.min(left, window.innerWidth - width - 12))
    let top = rect.top - 24
    const estimatedHeight = width * 0.56 + 190
    if (top + estimatedHeight > window.innerHeight - 16) top = Math.max(12, window.innerHeight - estimatedHeight - 16)
    setPreview({ left, top, width })
  }

  function scheduleOpen() {
    if (noPreview) return
    clearTimeout(closeTimer.current)
    clearTimeout(openTimer.current)
    openTimer.current = setTimeout(positionPreview, 320)
  }

  function scheduleClose() {
    clearTimeout(openTimer.current)
    closeTimer.current = setTimeout(() => setPreview(null), 140)
  }

  useEffect(() => {
    if (!preview) return
    const close = () => setPreview(null)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [preview])

  async function toggleList() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      if (inList) {
        if (listId) await api.delete(`/api/my-list/${listId}`)
        else await api.delete(`/api/my-list/${item.id}`)
        setInList(false)
        setListId(null)
      } else {
        const result = await api.post('/api/my-list', { title_id: item.id })
        setInList(true)
        setListId(result.item?.my_list_id || null)
      }
      window.dispatchEvent(new CustomEvent('netflix:mylist'))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function quickRate(value) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const result = await api.post(`/api/titles/${item.id}/rating`, { value })
      setUserRating(result.item?.user_rating ?? value)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function play(event) {
    event?.stopPropagation()
    setPreview(null)
    navigate(`/watch/${item.id}`)
  }

  function expand(event) {
    event?.stopPropagation()
    setPreview(null)
    onOpen?.(item)
  }

  const actionButtons = (
    <>
      <button type="button" className="round-action play-action" onClick={play} aria-label={`Play ${item.name}`}><Icon name="play" size={20} /></button>
      <button type="button" className={`round-action ${inList ? 'selected' : ''}`} onClick={(event) => { event.stopPropagation(); toggleList() }} aria-label={inList ? 'Remove from My List' : 'Add to My List'} disabled={busy}>
        <Icon name={inList ? 'check' : 'plus'} size={20} />
      </button>
      <button type="button" className={`round-action ${userRating === 1 ? 'selected' : ''}`} onClick={(event) => { event.stopPropagation(); quickRate(1) }} aria-label="I like this" disabled={busy}>
        <Icon name="thumbs-up" size={19} />
      </button>
      <button type="button" className="round-action expand-action" onClick={expand} aria-label={`More information about ${item.name}`}><Icon name="chevron-down" size={20} /></button>
    </>
  )

  const card = (
    <div
      ref={anchorRef}
      className={`title-card ${top10Rank ? 'ranked-card' : ''} ${className}`}
      onMouseEnter={scheduleOpen}
      onMouseLeave={scheduleClose}
      onClick={() => onOpen?.(item)}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onOpen?.(item) }}
    >
      {top10Rank && <span className="rank-number" aria-hidden="true">{top10Rank}</span>}
      <div className="poster-wrap">
        <img src={item.backdrop || item.poster} alt={item.name} loading="lazy" />
        <span className="card-static-info">
          <span className="card-static-title">{item.name}</span>
          <span className="card-static-meta">{item.kind === 'series' ? 'Series' : 'Film'} · {item.year}</span>
        </span>
        {item.top10_rank && <span className="top10-corner">TOP 10</span>}
        {inList && <span className="list-corner" title="In My List"><Icon name="check" size={14} /></span>}
        {showProgress && item.progress_percent != null && (
          <span className="card-progress"><span style={{ width: `${item.progress_percent}%` }} /></span>
        )}
        {!noPreview && (
          <div className="card-hover-shade">
            <span className="card-hover-title">{item.name}</span>
            <div className="card-hover-actions">{actionButtons}</div>
          </div>
        )}
      </div>
      {error && <span className="card-error">{error}</span>}
    </div>
  )

  const previewCard = preview ? createPortal(
    <div
      ref={previewRef}
      className="hover-preview"
      style={{ left: preview.left, top: preview.top, width: preview.width }}
      onMouseEnter={() => clearTimeout(closeTimer.current)}
      onMouseLeave={scheduleClose}
      onClick={() => onOpen?.(item)}
    >
      <div className="hover-preview-image" style={{ backgroundImage: `url(${item.backdrop || item.poster})` }}>
        <div className="hover-preview-top-fade" />
        <button type="button" className="hover-close" onClick={(event) => { event.stopPropagation(); setPreview(null) }} aria-label="Close preview"><Icon name="x" size={16} /></button>
        <div className="hover-preview-title">{item.name}</div>
      </div>
      <div className="hover-preview-body">
        <div className="hover-preview-actions">{actionButtons}</div>
        <div className="hover-preview-meta">
          <span className="match-score">{Math.round((item.rating || 0) * 10)}% Match</span>
          <span className="maturity-badge">{item.maturity_rating}</span>
          <span>{item.kind === 'series' ? `${item.seasons || 1} Seasons` : formatRuntime(item.duration)}</span>
        </div>
        <div className="hover-tags">{(item.genres || []).slice(0, 3).map((genre) => <span key={genre}>{genre}</span>)}</div>
      </div>
    </div>,
    document.body,
  ) : null

  return <>{card}{previewCard}</>
}
