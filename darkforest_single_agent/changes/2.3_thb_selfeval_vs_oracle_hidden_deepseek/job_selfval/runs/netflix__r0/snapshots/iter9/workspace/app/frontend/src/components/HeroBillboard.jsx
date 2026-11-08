import { useNavigate } from 'react-router-dom'
import Icon from './Icon.jsx'

export default function HeroBillboard({ title, eyebrow, onMoreInfo, pageLabel, children, compact = false, topBar = null }) {
  const navigate = useNavigate()
  if (!title) {
    return (
      <section className="hero hero-empty">
        <div className="hero-content">
          <p className="hero-eyebrow">{eyebrow || 'NETFLIX'}</p>
          <h1>{pageLabel || 'Browse'}</h1>
          <p className="hero-synopsis">There are no titles available in this section yet.</p>
        </div>
      </section>
    )
  }
  return (
    <section className={`hero ${compact ? 'compact' : ''}`} style={{ backgroundImage: `url(${title.backdrop || title.poster})` }}>
      <div className="hero-vignette" />
      <div className="hero-fade" />
      {topBar}
      <div className="hero-content">
        <p className="hero-eyebrow"><span className="netflix-n">N</span> {eyebrow || (title.kind === 'series' ? 'SERIES' : 'FILM')}</p>
        <h1 className="hero-title">{title.name}</h1>
        <div className="hero-meta">
          <span className="match-score">{Math.round((title.rating || 0) * 10)}% Match</span>
          <span>{title.year}</span>
          <span className="maturity-badge">{title.maturity_rating}</span>
          <span>{title.kind === 'series' ? `${title.seasons || 1} Season${(title.seasons || 1) === 1 ? '' : 's'}` : formatRuntime(title.duration)}</span>
          {title.top10_rank && <span className="top10-badge">TOP 10</span>}
        </div>
        <p className="hero-synopsis">{title.synopsis}</p>
        <div className="hero-actions">
          <button type="button" className="btn btn-play" onClick={() => navigate(`/watch/${title.id}`)}>
            <Icon name="play" size={24} /> Play
          </button>
          <button type="button" className="btn btn-info" onClick={() => onMoreInfo?.(title)}>
            <Icon name="info" size={24} /> More Info
          </button>
        </div>
        {children}
      </div>
      <div className="hero-side-badge">
        <span className="maturity-large">{title.maturity_rating}</span>
      </div>
    </section>
  )
}

export function formatRuntime(seconds) {
  const value = Number(seconds || 0)
  if (!value) return '—'
  const hours = Math.floor(value / 3600)
  const minutes = Math.round((value % 3600) / 60)
  if (hours && minutes) return `${hours}h ${minutes}m`
  if (hours) return `${hours}h`
  return `${minutes}m`
}
