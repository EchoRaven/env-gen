import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import Icon from './Icon.jsx'
import RateDialog from './RateDialog.jsx'
import { formatRuntime } from './HeroBillboard.jsx'

function episodeRuntime(seconds) {
  const minutes = Math.max(1, Math.round(Number(seconds || 0) / 60))
  return `${minutes}m`
}

export default function TitleModal() {
  const [params] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { api, token } = useAuth()
  const titleId = params.get('title')
  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [season, setSeason] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [rateOpen, setRateOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const close = useCallback(() => {
    const next = new URLSearchParams(params)
    next.delete('title')
    const qs = next.toString()
    if (location.pathname.startsWith('/watch')) navigate('/browse')
    else navigate(`${location.pathname}${qs ? `?${qs}` : ''}`)
  }, [params, location.pathname, navigate])

  useEffect(() => {
    if (!titleId || !token) {
      setTitle(null)
      setEpisodes([])
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    setTitle(null)
    Promise.all([
      api.get(`/api/titles/${titleId}`),
      api.get(`/api/titles/${titleId}/episodes`),
    ]).then(([titleResult, episodeResult]) => {
      if (cancelled) return
      setTitle(titleResult.item)
      const nextEpisodes = episodeResult.items || []
      setEpisodes(nextEpisodes)
      setSeason(nextEpisodes[0]?.season || 1)
    }).catch((err) => {
      if (!cancelled) setError(err.message)
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [titleId, token, api])

  useEffect(() => {
    if (!titleId) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    function onKey(event) {
      if (event.key === 'Escape') {
        if (rateOpen) setRateOpen(false)
        else close()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previous
      document.removeEventListener('keydown', onKey)
    }
  }, [titleId, close, rateOpen])

  const seasons = useMemo(() => [...new Set(episodes.map((episode) => episode.season))].sort((a, b) => a - b), [episodes])
  const visibleEpisodes = episodes.filter((episode) => episode.season === season)

  if (!titleId || !token) return null
  if (!title && !loading && !error) return null

  async function toggleList() {
    if (!title || busy) return
    setBusy(true)
    try {
      if (title.in_my_list) {
        await api.delete(`/api/my-list/${title.my_list_id || title.id}`)
        setTitle({ ...title, in_my_list: false, my_list_id: null })
      } else {
        const result = await api.post('/api/my-list', { title_id: title.id })
        setTitle({ ...title, in_my_list: true, my_list_id: result.item?.my_list_id })
      }
      window.dispatchEvent(new CustomEvent('netflix:mylist'))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function quickRate(value) {
    if (!title || busy) return
    setBusy(true)
    try {
      const result = await api.post(`/api/titles/${title.id}/rating`, { value })
      setTitle({ ...title, user_rating: result.item?.user_rating ?? value })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function play() {
    if (!title) return
    const firstEpisode = episodes[0]
    navigate(`/watch/${title.id}${firstEpisode ? `?ep=${firstEpisode.id}` : ''}`)
  }

  function playEpisode(episode) {
    navigate(`/watch/${title.id}?ep=${episode.id}`)
  }

  return createPortal(
    <div className="title-modal-overlay" role="dialog" aria-modal="true" aria-label={title?.name || 'Title details'} onClick={(event) => { if (event.target === event.currentTarget) close() }}>
      <div className="title-modal">
        <button type="button" className="modal-close" onClick={close} aria-label="Close title details"><Icon name="x" size={24} /></button>
        {loading && <div className="modal-loading">Loading details…</div>}
        {error && <div className="modal-loading form-error">{error}</div>}
        {title && (
          <>
            <div className="modal-hero" style={{ backgroundImage: `url(${title.backdrop || title.poster})` }}>
              <div className="modal-hero-gradient" />
              <div className="modal-hero-content">
                <h1>{title.name}</h1>
                <div className="modal-actions">
                  <button type="button" className="btn btn-play" onClick={play}><Icon name="play" size={23} /> {title.progress_seconds > 0 ? 'Resume' : 'Play'}</button>
                  <button type="button" className={`round-action modal-round ${title.in_my_list ? 'selected' : ''}`} onClick={toggleList} aria-label={title.in_my_list ? 'Remove from My List' : 'Add to My List'} disabled={busy}>
                    <Icon name={title.in_my_list ? 'check' : 'plus'} size={22} />
                  </button>
                  <button type="button" className={`round-action modal-round ${[1, 2].includes(title.user_rating) ? 'selected' : ''}`} onClick={() => quickRate(1)} aria-label="I like this" disabled={busy}><Icon name="thumbs-up" size={21} /></button>
                  <button type="button" className={`round-action modal-round ${title.user_rating === -1 ? 'selected' : ''}`} onClick={() => quickRate(-1)} aria-label="Not for me" disabled={busy}><Icon name="thumbs-down" size={21} /></button>
                  <button type="button" className="rate-link" onClick={() => setRateOpen(true)}>Rate this title</button>
                </div>
              </div>
            </div>
            <div className="modal-detail-grid">
              <div className="modal-main">
                <div className="modal-meta">
                  <span className="match-score">{Math.round((title.rating || 0) * 10)}% Match</span>
                  <span>{title.year}</span>
                  <span className="maturity-badge">{title.maturity_rating}</span>
                  <span>{title.kind === 'series' ? `${title.seasons} Season${title.seasons === 1 ? '' : 's'}` : formatRuntime(title.duration)}</span>
                  <span className="hd-badge">HD</span>
                </div>
                <p className="modal-synopsis">{title.synopsis}</p>
              </div>
              <aside className="modal-aside">
                <p><span className="aside-label">Genres</span> {(title.genres || []).join(', ') || '—'}</p>
                <p><span className="aside-label">Cast</span> —</p>
                <p><span className="aside-label">Original language</span> {title.language_name || title.language || '—'}</p>
                <p><span className="aside-label">Maturity rating</span> {title.maturity_rating}</p>
                <p><span className="aside-label">This title is</span> {title.kind === 'series' ? 'A TV series' : 'A film'}</p>
              </aside>
            </div>
            {title.kind === 'series' && episodes.length > 0 && (
              <section className="episodes-section">
                <div className="episodes-header">
                  <h2>Episodes</h2>
                  {seasons.length > 1 && (
                    <label className="season-select">
                      <span>Season</span>
                      <select value={season} onChange={(event) => setSeason(Number(event.target.value))} aria-label="Select season">
                        {seasons.map((value) => <option key={value} value={value}>Season {value}</option>)}
                      </select>
                    </label>
                  )}
                </div>
                <div className="episode-list">
                  {visibleEpisodes.map((episode, index) => (
                    <button type="button" className="episode-row" key={episode.id} onClick={() => playEpisode(episode)}>
                      <span className="episode-number">{index + 1}</span>
                      <img src={episode.thumbnail || title.backdrop} alt="" loading="lazy" />
                      <span className="episode-info">
                        <span className="episode-title-line"><strong>{episode.name}</strong><small>{title.maturity_rating} · {episodeRuntime(episode.duration)}</small></span>
                        <span className="episode-synopsis">{episode.synopsis}</span>
                      </span>
                      <span className="episode-play"><Icon name="play" size={24} /></span>
                    </button>
                  ))}
                </div>
              </section>
            )}
            {title.kind !== 'series' && (
              <section className="about-section">
                <h2>About <span>{title.name}</span></h2>
                <p className="about-genres"><span className="aside-label">Genres</span> {(title.genres || []).join(', ') || '—'}</p>
                <p className="about-genres"><span className="aside-label">This film is</span> {title.genre || '—'}</p>
              </section>
            )}
          </>
        )}
      </div>
      {rateOpen && title && (
        <RateDialog
          title={title}
          currentValue={title.user_rating}
          onClose={() => setRateOpen(false)}
          onRated={(value) => setTitle({ ...title, user_rating: value })}
        />
      )}
    </div>,
    document.body,
  )
}
