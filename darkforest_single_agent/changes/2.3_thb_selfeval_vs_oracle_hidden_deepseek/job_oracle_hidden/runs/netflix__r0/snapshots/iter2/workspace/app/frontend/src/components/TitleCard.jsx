import { useState } from 'react'
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
  const durationSeconds = Math.max(1, (title.duration || 45) * 60)
  const progress = showProgress ? Math.min(100, Math.max(2, (progressSeconds / durationSeconds) * 100)) : 0
  const remaining = Math.max(1, Math.round((durationSeconds - progressSeconds) / 60))

  return (
    <article
      className={`title-card ${hovered ? 'hovered' : ''}`}
      style={{ '--card-index': index }}
      tabIndex={0}
      role="button"
      aria-label={`${title.name}, ${title.year}`}
      onClick={() => onOpen?.(title)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen?.(title)
        }
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setHovered(false)
      }}
    >
      <div className="card-poster-shell">
        <img className="card-poster" src={title.backdrop || title.poster} alt="" loading="lazy" />
        <span className="card-title-fallback">{title.name}</span>
        {showProgress ? (
          <span className="card-progress" aria-label={`${Math.round(progress)} percent watched`}>
            <span style={{ width: `${progress}%` }} />
          </span>
        ) : null}
        <div className="card-hover-preview">
          <div className="card-preview-image">
            <img src={title.backdrop || title.poster} alt="" loading="lazy" />
            <span className="card-preview-shade" />
            <span className="card-preview-title">{title.name}</span>
          </div>
          <div className="card-preview-body">
            <div className="card-preview-actions">
              <button
                className="round-action play-round"
                aria-label={`Play ${title.name}`}
                onClick={(event) => {
                  event.stopPropagation()
                  onPlay?.(title)
                }}
              >
                <AssetIcon name="play" size={18} />
              </button>
              <button
                className={`round-action ${inList ? 'active' : ''}`}
                aria-label={inList ? `Remove ${title.name} from My List` : `Add ${title.name} to My List`}
                onClick={(event) => {
                  event.stopPropagation()
                  onToggleList?.(title, inList)
                }}
              >
                {inList ? <span className="check-glyph">✓</span> : <AssetIcon name="plus" size={18} />}
              </button>
              <button
                className="round-action"
                aria-label={`Rate ${title.name}`}
                onClick={(event) => {
                  event.stopPropagation()
                  onRate?.(title)
                }}
              >
                <AssetIcon name="thumbs_up" size={18} />
              </button>
              <button
                className="round-action expand-round"
                aria-label={`More information about ${title.name}`}
                onClick={(event) => {
                  event.stopPropagation()
                  onOpen?.(title)
                }}
              >
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
                {(title.genres || []).slice(0, 2).map((genre) => (
                  <span key={genre}>{genre}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      <p className="card-fallback-title">{title.name}</p>
    </article>
  )
}

export function Top10Card({ title, rank, onOpen }) {
  return (
    <article
      className="top10-card"
      role="button"
      tabIndex={0}
      aria-label={`Number ${rank}: ${title.name}`}
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
