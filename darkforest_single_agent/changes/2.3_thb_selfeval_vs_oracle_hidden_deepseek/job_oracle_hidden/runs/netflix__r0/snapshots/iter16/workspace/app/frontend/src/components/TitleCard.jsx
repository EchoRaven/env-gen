import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AssetIcon } from '../icons'
import { formatClock } from '../utils'

export function TitleCard({
  title,
  inList = false,
  showProgress = false,
  progressSeconds = 0,
  onOpen,
  onPlay,
  onToggleList,
  onRate,
  index = 0,
}) {
  const [hovered, setHovered] = useState(false)
  const [previewRect, setPreviewRect] = useState(null)
  const closeTimer = useRef(null)
  const cardRef = useRef(null)
  const durationSeconds = Math.max(1, (title.duration || 45) * 60)
  const progress = showProgress ? Math.min(100, Math.max(2, (progressSeconds / durationSeconds) * 100)) : 0
  const remaining = Math.max(1, Math.round((durationSeconds - progressSeconds) / 60))

  const cancelClose = () => window.clearTimeout(closeTimer.current)
  const scheduleClose = () => {
    cancelClose()
    closeTimer.current = window.setTimeout(() => setHovered(false), 180)
  }
  const openPreview = () => {
    cancelClose()
    const rect = cardRef.current?.getBoundingClientRect()
    if (!rect) return
    setPreviewRect(rect)
    setHovered(true)
  }

  let previewStyle = null
  if (previewRect) {
    const previewWidth = Math.min(460, Math.max(350, previewRect.width * 1.36))
    const previewHeight = previewWidth * 0.5625 + 132
    const left = Math.max(12, Math.min(previewRect.left - (previewWidth - previewRect.width) / 2, window.innerWidth - previewWidth - 12))
    const top = Math.max(78, Math.min(previewRect.top - 26, window.innerHeight - previewHeight - 14))
    previewStyle = { left, top, width: previewWidth }
  }

  const runAction = (event, action) => {
    event.stopPropagation()
    action?.()
  }

  return (
    <>
      <article
        ref={cardRef}
        className="title-card"
        style={{ '--card-index': index }}
        tabIndex={0}
        role="button"
        aria-label={title.name + ', ' + title.year}
        onClick={() => onOpen?.(title)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onOpen?.(title)
          }
        }}
        onMouseEnter={openPreview}
        onMouseLeave={scheduleClose}
        onFocus={openPreview}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) scheduleClose()
        }}
      >
        <div className="card-poster-shell">
          <img className="card-poster" src={title.backdrop || title.poster} alt="" loading="lazy" />
          {title.top10_rank ? <span className="card-top10-badge"><strong>TOP</strong> 10</span> : null}
          <span className="card-title-fallback">{title.name}</span>
          {showProgress ? (
            <span className="card-progress" aria-label={Math.round(progress) + ' percent watched'}>
              <span style={{ width: progress + '%' }} />
            </span>
          ) : null}
        </div>
        <p className="card-fallback-title">{title.name}</p>
      </article>
      {hovered && previewStyle ? createPortal(
        <div
          className="card-hover-float"
          style={previewStyle}
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
          onClick={(event) => { event.stopPropagation(); onOpen?.(title) }}
        >
          <div className="float-preview-image">
            <img src={title.backdrop || title.poster} alt="" />
            <span className="float-preview-shade" />
            <span className="float-preview-title">{title.name}</span>
          </div>
          <div className="float-preview-body">
            <div className="card-preview-actions">
              <button className="round-action play-round" aria-label={'Play ' + title.name} onClick={(event) => runAction(event, () => onPlay?.(title))}>
                <AssetIcon name="play" size={18} />
              </button>
              <button
                className={'round-action ' + (inList ? 'active' : '')}
                aria-label={inList ? 'Remove from My List' : 'Add to My List'}
                onClick={(event) => runAction(event, () => onToggleList?.(title, inList))}
              >
                {inList ? <span className="check-glyph">✓</span> : <AssetIcon name="plus" size={18} />}
              </button>
              <button className="round-action" aria-label={'Rate ' + title.name} onClick={(event) => runAction(event, () => onRate?.(title))}>
                <AssetIcon name="thumbs_up" size={18} />
              </button>
              <button className="round-action expand-round" aria-label={'More information about ' + title.name} onClick={(event) => runAction(event, () => onOpen?.(title))}>
                <span aria-hidden="true">⌄</span>
              </button>
            </div>
            <div className="card-preview-meta">
              <span className="match-score">{Number(title.rating || 0).toFixed(1)} rating</span>
              <span className="maturity-inline">{title.maturity_rating}</span>
              <span>{title.year}</span>
              <span className="hd-label">HD</span>
            </div>
            {showProgress ? (
              <p className="preview-progress-copy">{formatClock(progressSeconds)} watched · {remaining}m left</p>
            ) : (
              <div className="preview-tags">
                {(title.genres || []).slice(0, 3).map((genre) => <span key={genre}>{genre}</span>)}
              </div>
            )}
          </div>
        </div>,
        document.body,
      ) : null}
    </>
  )
}

export function Top10Card({ title, rank, onOpen }) {
  return (
    <article
      className="top10-card"
      role="button"
      tabIndex={0}
      aria-label={'Number ' + rank + ': ' + title.name}
      onClick={() => onOpen?.(title)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') onOpen?.(title)
      }}
    >
      <span className="top10-number" aria-hidden="true">{rank}</span>
      <div className="top10-poster">
        <img src={title.backdrop || title.poster} alt="" loading="lazy" />
        <span className="top10-title">{title.name}</span>
      </div>
    </article>
  )
}
