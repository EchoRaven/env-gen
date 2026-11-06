import { useNavigate } from 'react-router-dom'
import Icon from './Icon'
import { mediaUrl, matchPct } from '../lib/util'
import { openTitleModal } from '../lib/modalStore'

export default function Hero({ title, compact = false }) {
  const nav = useNavigate()
  const match = matchPct(title.rating)
  return (
    <div className="hero" style={compact ? { height: '62vh', minHeight: 400 } : undefined}>
      <div style={{ position: 'absolute', inset: 0, backgroundImage: `url(${mediaUrl(title.backdrop || title.poster)})`, backgroundSize: 'cover', backgroundPosition: 'center 20%' }} />
      <div className="hero-content">
        <h1 className="hero-title">{title.name}</h1>
        <div className="hero-meta">
          {match != null && <span className="match">{match}% Match</span>}
          <span style={{ color: '#cfcfcf' }}>{title.year}</span>
          {title.top10_rank && <span style={{ color: '#e50914', fontWeight: 600, fontSize: 0.85 }}>Top {title.top10_rank} · {title.kind === 'series' ? 'TV Show' : 'Movie'}</span>}
        </div>
        {title.synopsis && <p className="hero-synopsis">{title.synopsis}</p>}
        <div className="hero-actions">
          <button className="btn btn-play" onClick={() => nav(`/watch/${title.id}`)}>
            <Icon name="play" size={26} /> Play
          </button>
          <button className="btn btn-info" onClick={() => openTitleModal(title.id)}>
            <Icon name="info" size={24} /> More Info
          </button>
          <span className="maturity-badge">{title.maturity_rating || '—'}</span>
        </div>
      </div>
    </div>
  )
}
