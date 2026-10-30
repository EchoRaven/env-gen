import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSession } from '../session.jsx'
import { Icon } from '../icons.jsx'
import { lengthLabel } from '../format.js'

// Hero billboard: real backdrop, then the title's real clip (muted) fades in.
export default function Billboard({ t, variant = 'inset', children }) {
  const navigate = useNavigate()
  const { openTitle } = useSession()
  const [showVideo, setShowVideo] = useState(false)
  const [muted, setMuted] = useState(true)
  const [ended, setEnded] = useState(false)
  const vid = useRef(null)
  useEffect(() => {
    setShowVideo(false); setEnded(false)
    const id = setTimeout(() => setShowVideo(true), 1800)
    return () => clearTimeout(id)
  }, [t && t.id])
  if (!t) return <div className={`billboard ${variant} empty`}>{children}</div>
  const replay = () => { setEnded(false); if (vid.current) { vid.current.currentTime = 0; vid.current.play() } }
  return (
    <section className={`billboard ${variant}`}>
      <img className="bb-img" src={t.backdrop} alt="" />
      {showVideo && t.video_url && (
        <video ref={vid} className={`bb-video ${ended ? 'done' : ''}`} src={t.video_url} autoPlay muted={muted} playsInline
          onPlaying={(e) => e.currentTarget.classList.add('on')} onEnded={() => setEnded(true)} />
      )}
      <div className="bb-shade" />
      {children}
      <div className="bb-content">
        <h1 className="bb-title">{t.name}</h1>
        <div className="bb-meta">
          {[t.genres?.[0]?.name || t.genre, t.year, lengthLabel(t), t.maturity_rating].filter(Boolean)
            .map((x, i) => <span key={i}>{i > 0 && <i className="dot" />}{x}</span>)}
        </div>
        <p className="bb-synopsis">{t.synopsis}</p>
        <div className="bb-actions">
          <button className="btn-play" onClick={() => navigate(`/watch/${t.id}`)}>
            <Icon name="play" size={28} /> Play
          </button>
          <button className="btn-info" onClick={() => openTitle(t.id)}>
            <Icon name="info" size={26} /> More Info
          </button>
        </div>
      </div>
      <div className="bb-side">
        {showVideo && (
          <button className="mute-btn" aria-label={ended ? 'Replay' : muted ? 'Unmute' : 'Mute'}
            onClick={() => (ended ? replay() : setMuted((m) => !m))}>
            <Icon name={ended ? 'refresh' : muted ? 'volumeOff' : 'volumeHigh'} size={22} />
          </button>
        )}
        {variant !== 'inset' && <span className="bb-maturity">{t.maturity_rating}</span>}
        {variant === 'inset' && t.top10_rank && (
          <span className="bb-flag"><Icon name="newEpisode" size={22} /> #{t.top10_rank} in {t.kind === 'series' ? 'TV Shows' : 'Movies'} Today</span>
        )}
      </div>
    </section>
  )
}
