import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import { CaretDown, Icon } from '../icons.jsx'
import { clipLength, languageName, lengthLabel } from '../format.js'
import { ListButton } from './TitleCard.jsx'
import RateDialog from './RateDialog.jsx'

function SeasonSelect({ seasons, value, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  if (seasons.length <= 1) return <span className="season-static">Season {value}</span>
  return (
    <div className="season-select" ref={ref}>
      <button className="season-btn" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}>
        Season {value} <CaretDown size={14} />
      </button>
      {open && (
        <ul className="season-list" role="listbox">
          {seasons.map((s) => (
            <li key={s}>
              <button className={s === value ? 'on' : ''} onClick={() => { onChange(s); setOpen(false) }}>
                Season {s}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function MoreLikeThis({ t }) {
  const { openTitle } = useSession()
  const g = t.genres?.[0]
  const { data } = useAsync(() => (g ? api.genreTitles(g.id) : Promise.resolve({ items: [] })), [t.id])
  const items = (data?.items || []).filter((x) => x.id !== t.id).slice(0, 9)
  if (!g) return null
  return (
    <div className="mlt">
      <h3>More Like This</h3>
      {items.length === 0 && <p className="muted">No other {g.name} titles in the catalog.</p>}
      <div className="mlt-grid">
        {items.map((x) => (
          <button key={x.id} className="mlt-card" onClick={() => openTitle(x.id)}>
            <div className="mlt-img"><img src={x.backdrop} alt="" loading="lazy" /><span className="card-title">{x.name}</span></div>
            <div className="mlt-body">
              <div className="mlt-meta"><span className="maturity">{x.maturity_rating}</span><span>{x.year}</span></div>
              <p>{x.synopsis}</p>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

export default function DetailModal({ id }) {
  const { closeTitle, ratingOf, profileId } = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const { data, error, loading } = useAsync(() => api.title(id), [id, profileId])
  const t = data?.item
  const eps = useAsync(() => (t && t.kind === 'series' ? api.episodes(t.id) : Promise.resolve(null)), [t && t.id])
  const [season, setSeason] = useState(1)
  const [muted, setMuted] = useState(true)
  const [rateOpen, setRateOpen] = useState(false)
  const box = useRef(null)

  useEffect(() => { setSeason(1); box.current?.scrollTo?.(0, 0) }, [id])
  useEffect(() => {
    document.body.classList.add('modal-open')
    const k = (e) => { if (e.key === 'Escape' && !rateOpen) closeTitle() }
    window.addEventListener('keydown', k)
    return () => { document.body.classList.remove('modal-open'); window.removeEventListener('keydown', k) }
  }, [closeTitle, rateOpen])

  const seasons = eps.data?.seasons || []
  const seasonEps = useMemo(() => (eps.data?.items || []).filter((e) => e.season === season), [eps.data, season])
  const r = t ? ratingOf(t) : null
  const thumbIcon = r === -1 ? 'thumbsDown' : r === 2 ? 'thumbsUpTwo' : 'thumbsUp'
  const play = (ep) => navigate(`/watch/${t.id}${ep ? `?episode=${ep.id}` : ''}`, { state: { from: location.pathname + location.search } })

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) closeTitle() }}>
      <div className="detail-modal" ref={box} role="dialog" aria-modal="true" aria-label={t ? t.name : 'Title details'}>
        <button className="modal-close" aria-label="Close" onClick={closeTitle}><Icon name="close" size={22} /></button>
        {loading && <div className="modal-loading"><div className="spinner" /></div>}
        {error && <div className="modal-error"><h2>Title unavailable</h2><p>{error.message}</p></div>}
        {t && (
          <>
            <div className="dm-hero">
              <img src={t.backdrop} alt="" />
              {t.video_url && <video src={t.video_url} autoPlay muted={muted} loop playsInline onPlaying={(e) => e.currentTarget.classList.add('on')} />}
              <div className="dm-shade" />
              <div className="dm-hero-content">
                <h2 className="dm-title">{t.name}</h2>
                <div className="dm-actions">
                  <button className="btn-play rect" onClick={() => play(null)}>
                    <Icon name="play" size={30} /> {t.progress_seconds ? 'Resume' : 'Play'}
                  </button>
                  <ListButton title={t} size="lg" />
                  <button className={`circle-btn lg ${r ? 'rated' : ''}`} aria-label="Rate this title" onClick={() => setRateOpen(true)}>
                    <Icon name={thumbIcon} size={24} />
                  </button>
                </div>
              </div>
              {t.video_url && (
                <button className="mute-btn dm-mute" aria-label={muted ? 'Unmute' : 'Mute'} onClick={() => setMuted((m) => !m)}>
                  <Icon name={muted ? 'volumeOff' : 'volumeHigh'} size={22} />
                </button>
              )}
            </div>
            <div className="dm-body">
              <div className="dm-cols">
                <div className="dm-left">
                  <div className="dm-meta">
                    <span>{t.year}</span>
                    <span>{lengthLabel(t)}</span>
                    {t.kind === 'movie' && t.duration ? <span>Clip {clipLength(t.duration)}</span> : null}
                    <span className="hd">HD</span>
                    <Icon name="subtitles" size={20} className="dim" />
                  </div>
                  <div className="dm-meta2"><span className="maturity">{t.maturity_rating}</span></div>
                  {t.top10_rank && (
                    <div className="dm-top10"><span className="top10-badge static"><small>TOP</small>10</span>
                      #{t.top10_rank} in {t.kind === 'series' ? 'TV Shows' : 'Movies'} Today</div>
                  )}
                  <p className="dm-synopsis">{t.synopsis || '—'}</p>
                </div>
                <div className="dm-right">
                  <p><span className="label">Genres: </span>
                    {t.genres.length ? t.genres.map((g, i) => (
                      <span key={g.id}>{i > 0 && ', '}<Link to={`/browse/genre/${g.id}${t.kind === 'series' ? '?kind=series' : '?kind=movie'}`} onClick={() => document.body.classList.remove('modal-open')}>{g.name}</Link></span>
                    )) : '—'}
                  </p>
                  <p><span className="label">Original language: </span>{languageName(t.language)}</p>
                  <p><span className="label">Audience score: </span>{t.rating ? `${t.rating.toFixed(1)} / 10` : '—'}</p>
                  <p><span className="label">Your rating: </span>{r === -1 ? 'Not for me' : r === 1 ? 'I like this' : r === 2 ? 'Love this!' : 'Not rated'}</p>
                </div>
              </div>

              {t.kind === 'series' && (
                <div className="episodes">
                  <div className="ep-head">
                    <h3>Episodes</h3>
                    <SeasonSelect seasons={seasons} value={season} onChange={setSeason} />
                  </div>
                  <div className="ep-sub">Season {season}: <span className="maturity">{t.maturity_rating}</span></div>
                  {eps.loading && <p className="muted">Loading episodes…</p>}
                  {!eps.loading && seasonEps.length === 0 && <p className="muted">No episodes available.</p>}
                  {seasonEps.map((e) => (
                    <button key={e.id} className={`episode ${t.resume_episode_id === e.id ? 'current' : ''}`} onClick={() => play(e)}>
                      <span className="ep-num">{e.number}</span>
                      <span className="ep-thumb">
                        <img src={e.thumbnail} alt="" loading="lazy" />
                        <span className="ep-play"><Icon name="play" size={22} /></span>
                      </span>
                      <span className="ep-info">
                        <span className="ep-top"><b>{e.name}</b><span>{clipLength(e.duration)}</span></span>
                        {e.synopsis && <span className="ep-syn">{e.synopsis}</span>}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {t.kind === 'movie' && <MoreLikeThis t={t} />}
              <div className="dm-about">
                <h3>About <b>{t.name}</b></h3>
                <p><span className="label">Genres: </span>{t.genres.map((g) => g.name).join(', ') || '—'}</p>
                <p><span className="label">Released: </span>{t.year || '—'}</p>
                <p><span className="label">Maturity rating: </span><span className="maturity">{t.maturity_rating}</span></p>
              </div>
            </div>
          </>
        )}
      </div>
      {rateOpen && t && <RateDialog title={t} onClose={() => setRateOpen(false)} />}
    </div>
  )
}
