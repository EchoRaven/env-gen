import { useNavigate } from 'react-router-dom'
import { AssetIcon, NIcon } from '../icons'
import { formatDuration } from '../utils'

export function Billboard({ title, label, onPlay, compact = false, rankLabel }) {
  const navigate = useNavigate()
  if (!title) {
    return (
      <section className="billboard billboard-empty">
        <div className="billboard-content">
          <p className="billboard-kicker">NETFLIX</p>
          <h1>There is nothing to watch here yet.</h1>
          <p className="billboard-synopsis">Titles will appear when they are available in the catalog.</p>
        </div>
      </section>
    )
  }

  const openDetails = () => navigate(`/title/${title.id}`, { state: { from: window.location.pathname } })
  const play = () => {
    if (onPlay) onPlay(title)
    else navigate(`/watch/${title.id}`)
  }

  return (
    <section className={`billboard ${compact ? 'billboard-compact' : ''}`} style={{ '--hero-image': `url(${title.backdrop || title.poster})` }}>
      <div className="billboard-image" aria-hidden="true" />
      <div className="billboard-vignette" aria-hidden="true" />
      <div className="billboard-content">
        <div className="billboard-kicker">
          <NIcon size={22} />
          <span>{label || (title.kind === 'series' ? 'SERIES' : 'FILM')}</span>
        </div>
        <h1>{title.name}</h1>
        {rankLabel ? <p className="billboard-rank">{rankLabel}</p> : null}
        <div className="billboard-meta">
          <span className="match-score">{Number(title.rating || 0).toFixed(1)} rating</span>
          <span>{title.year}</span>
          <span className="maturity-badge">{title.maturity_rating}</span>
          <span>{title.kind === 'series' ? `${title.seasons || 1} Season${(title.seasons || 1) === 1 ? '' : 's'}` : formatDuration(title.duration)}</span>
          <span className="hd-label">HD</span>
        </div>
        <p className="billboard-synopsis">{title.synopsis}</p>
        <div className="billboard-actions">
          <button className="button button-white play-button" onClick={play}>
            <AssetIcon name="play" size={22} />
            Play
          </button>
          <button className="button button-gray more-info-button" onClick={openDetails}>
            <span className="info-glyph" aria-hidden="true">i</span>
            More Info
          </button>
        </div>
      </div>
      <div className="billboard-rating">
        <span className="maturity-badge large">{title.maturity_rating}</span>
      </div>
    </section>
  )
}
