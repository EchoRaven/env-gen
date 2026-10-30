import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import { EpisodesIcon, ExitFullscreenIcon, FullscreenIcon, Icon, NextEpisodeIcon, SkipIcon } from '../icons.jsx'
import { clipLength, languageName, timecode } from '../format.js'

export default function Player() {
  const { titleId } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { token, profileId } = useSession()
  const { data, error } = useAsync(() => api.title(titleId), [titleId, profileId])
  const t = data?.item
  const eps = useAsync(() => (t && t.kind === 'series' ? api.episodes(t.id) : Promise.resolve(null)), [t && t.id])
  const episodes = eps.data?.items || []
  const epParam = params.get('episode')
  const episode = useMemo(() => {
    if (!t || t.kind !== 'series' || episodes.length === 0) return null
    const want = epParam ? Number(epParam) : t.resume_episode_id
    return episodes.find((e) => e.id === want) || episodes[0]
  }, [t, episodes, epParam])
  const nextEp = episode ? episodes[episodes.indexOf(episode) + 1] : null

  const video = useRef(null)
  const wrap = useRef(null)
  const hideTimer = useRef(null)
  const lastSaved = useRef(0)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [buffered, setBuffered] = useState(0)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [showUI, setShowUI] = useState(true)
  const [panel, setPanel] = useState(null) // 'episodes' | 'audio' | 'volume' | null
  const [fs, setFs] = useState(false)
  const [ended, setEnded] = useState(false)
  const [hover, setHover] = useState(null)
  const [autoplayBlocked, setAutoplayBlocked] = useState(false)
  const [mediaError, setMediaError] = useState(false)

  const back = () => {
    if (location.state?.from) navigate(location.state.from)
    else if (window.history.length > 1) navigate(-1)
    else navigate('/browse')
  }

  const save = useCallback((pos) => {
    if (!t) return
    lastSaved.current = Date.now()
    api.saveProgress({ title_id: t.id, progress_seconds: Math.round(pos * 10) / 10, episode_id: episode ? episode.id : null })
      .catch(() => {})
  }, [t, episode])

  // Resume from the profile's saved position when it matches this title/episode.
  const onLoaded = () => {
    const v = video.current
    setDuration(v.duration || 0)
    const resumeOk = t && t.progress_seconds && (!episode || episode.id === t.resume_episode_id) && !epParam
    const sameEp = t && t.progress_seconds && episode && epParam && Number(epParam) === t.resume_episode_id
    if ((resumeOk || sameEp) && t.progress_seconds < (v.duration || 0) - 1) v.currentTime = t.progress_seconds
    v.play().then(() => setAutoplayBlocked(false)).catch(() => setAutoplayBlocked(true))
  }

  const poke = useCallback(() => {
    setShowUI(true)
    clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(() => { if (video.current && !video.current.paused) { setShowUI(false); setPanel(null) } }, 3200)
  }, [])

  const togglePlay = useCallback(() => {
    const v = video.current
    if (!v) return
    if (v.paused) { setEnded(false); v.play().catch(() => {}) } else v.pause()
    poke()
  }, [poke])
  const seekBy = useCallback((d) => {
    const v = video.current
    if (!v) return
    v.currentTime = Math.max(0, Math.min((v.duration || 0) - 0.05, v.currentTime + d))
    poke()
  }, [poke])
  const toggleMute = useCallback(() => {
    const v = video.current
    if (!v) return
    v.muted = !v.muted
    setMuted(v.muted)
    poke()
  }, [poke])
  const toggleFs = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen?.()
    else wrap.current?.requestFullscreen?.()
  }, [])

  useEffect(() => {
    const h = () => setFs(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', h)
    return () => document.removeEventListener('fullscreenchange', h)
  }, [])

  useEffect(() => {
    const k = (e) => {
      if (e.target.tagName === 'INPUT') return
      if (e.key === ' ' || e.key === 'k') { e.preventDefault(); togglePlay() }
      else if (e.key === 'ArrowLeft') seekBy(-10)
      else if (e.key === 'ArrowRight') seekBy(10)
      else if (e.key === 'm') toggleMute()
      else if (e.key === 'f') toggleFs()
      else if (e.key === 'Escape' && !document.fullscreenElement) { if (panel) setPanel(null); else back() }
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  })

  // Save on leave.
  useEffect(() => () => {
    const v = video.current
    if (v && v.currentTime > 0 && !v.ended) save(v.currentTime)
  }, [save])
  useEffect(() => () => clearTimeout(hideTimer.current), [])

  if (!token) return <Navigate to="/login" replace />

  const onTime = () => {
    const v = video.current
    setTime(v.currentTime)
    if (v.buffered.length) setBuffered(v.buffered.end(v.buffered.length - 1))
    if (Date.now() - lastSaved.current > 5000 && v.currentTime > 0.5) save(v.currentTime)
  }
  const onEnded = () => {
    setPlaying(false); setEnded(true); setShowUI(true)
    if (nextEp) {
      api.saveProgress({ title_id: t.id, progress_seconds: 0, episode_id: nextEp.id }).catch(() => {})
    } else if (t) {
      api.clearProgress(t.id).catch(() => {})
    }
  }
  const goEpisode = (e) => {
    setPanel(null); setEnded(false); setTime(0)
    const p = new URLSearchParams(params); p.set('episode', e.id); setParams(p, { replace: true, state: location.state })
  }
  const seekTo = (clientX, bar) => {
    const r = bar.getBoundingClientRect()
    const frac = Math.max(0, Math.min(1, (clientX - r.left) / r.width))
    if (video.current && duration) video.current.currentTime = frac * duration
  }
  const startDrag = (e) => {
    const bar = e.currentTarget
    seekTo(e.clientX, bar)
    const move = (ev) => seekTo(ev.clientX, bar)
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const setVol = (v) => {
    const el = video.current
    if (!el) return
    el.volume = v; el.muted = v === 0
    setVolume(v); setMuted(v === 0)
  }

  if (error) {
    return (
      <div className="player error">
        <button className="pl-back" aria-label="Back" onClick={back}><Icon name="arrowLeft" size={40} /></button>
        <div className="pl-error"><h2>This title isn’t available</h2><p>{error.message}</p></div>
      </div>
    )
  }

  const frac = duration ? time / duration : 0
  const vol = muted ? 0 : volume
  const label = episode ? <><b>{t.name}</b> <span>E{episode.number}</span> <span>{episode.name}</span></> : t ? <b>{t.name}</b> : null

  return (
    <div ref={wrap} className={`player ${showUI ? 'ui' : 'no-ui'}`} onMouseMove={poke} onTouchStart={poke}>
      {t && (
        <video ref={video} key={`${t.id}-${episode ? episode.id : 'm'}`} className="pl-video" src={t.video_url}
          poster={episode ? episode.thumbnail : t.backdrop} playsInline
          onLoadedMetadata={onLoaded} onTimeUpdate={onTime}
          onPlay={() => { setPlaying(true); setEnded(false); poke() }}
          onPause={() => { setPlaying(false); setShowUI(true); if (video.current) save(video.current.currentTime) }}
          onEnded={onEnded} onError={() => setMediaError(true)} onVolumeChange={(e) => { setVolume(e.currentTarget.volume); setMuted(e.currentTarget.muted) }}
          onClick={togglePlay} />
      )}
      {!t && <div className="pl-loading"><div className="spinner" /></div>}

      <div className="pl-top">
        <button className="pl-back" aria-label="Back to browse" onClick={back}><Icon name="arrowLeft" size={40} /></button>
      </div>

      {!playing && t && !ended && (
        <div className="pl-paused-info">
          <p className="pl-watching">You’re watching</p>
          <h1>{t.name}</h1>
          {episode && <h2>Season {episode.season}: Ep. {episode.number} “{episode.name}”</h2>}
          <p className="pl-desc">{(episode && episode.synopsis) || t.synopsis}</p>
          {mediaError && <p className="pl-media-error">This clip can’t be played in this browser (H.264/MP4 support is required).</p>}
          {autoplayBlocked && <button className="btn-white" onClick={togglePlay}><Icon name="play" size={22} /> Play</button>}
        </div>
      )}

      {ended && t && (
        <div className="pl-ended">
          {nextEp ? (
            <>
              <p>Up next</p>
              <h2>{t.name} · E{nextEp.number} {nextEp.name}</h2>
              <button className="btn-white" onClick={() => goEpisode(nextEp)}><Icon name="play" size={22} /> Play Next Episode</button>
            </>
          ) : (
            <>
              <h2>Thanks for watching {t.name}</h2>
              <div className="pl-ended-actions">
                <button className="btn-white" onClick={togglePlay}><Icon name="refresh" size={22} /> Watch Again</button>
                <button className="btn-grey" onClick={back}>Back to Browse</button>
              </div>
            </>
          )}
        </div>
      )}

      <div className="pl-bottom" onMouseEnter={() => clearTimeout(hideTimer.current)}>
        <div className="pl-progress-row">
          <div className="pl-bar" onPointerDown={startDrag}
            onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width))) }}
            onMouseLeave={() => setHover(null)} role="slider" aria-label="Seek" aria-valuemin={0}
            aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(time)} tabIndex={0}>
            <div className="pl-bar-buf" style={{ width: `${duration ? (buffered / duration) * 100 : 0}%` }} />
            <div className="pl-bar-fill" style={{ width: `${frac * 100}%` }} />
            <div className="pl-bar-knob" style={{ left: `${frac * 100}%` }} />
            {hover != null && duration > 0 && <div className="pl-bar-tip" style={{ left: `${hover * 100}%` }}>{timecode(hover * duration)}</div>}
          </div>
          <span className="pl-remaining">{timecode(Math.max(0, duration - time))}</span>
        </div>
        <div className="pl-controls">
          <div className="pl-left">
            <button className="pl-btn" aria-label={playing ? 'Pause' : 'Play'} onClick={togglePlay}>
              {playing ? <svg width="40" height="40" viewBox="0 0 24 24"><rect x="5" y="3" width="4.5" height="18" fill="currentColor" /><rect x="14.5" y="3" width="4.5" height="18" fill="currentColor" /></svg> : <Icon name="play" size={40} />}
            </button>
            <button className="pl-btn" aria-label="Back 10 seconds" onClick={() => seekBy(-10)}><SkipIcon dir="back" /></button>
            <button className="pl-btn" aria-label="Forward 10 seconds" onClick={() => seekBy(10)}><SkipIcon dir="fwd" /></button>
            <div className="pl-vol" onMouseEnter={() => setPanel('volume')} onMouseLeave={() => setPanel((p) => (p === 'volume' ? null : p))}>
              <button className="pl-btn" aria-label={vol === 0 ? 'Unmute' : 'Mute'} onClick={toggleMute}>
                <Icon name={vol === 0 ? 'volumeOff' : 'volumeHigh'} size={40} />
              </button>
              {panel === 'volume' && (
                <div className="pl-vol-pop">
                  <input type="range" min="0" max="1" step="0.05" value={vol} aria-label="Volume"
                    onChange={(e) => setVol(Number(e.target.value))} />
                </div>
              )}
            </div>
          </div>
          <div className="pl-title">{label}</div>
          <div className="pl-right">
            {nextEp && (
              <button className="pl-btn" aria-label="Next episode" title={`Next: E${nextEp.number}`} onClick={() => goEpisode(nextEp)}>
                <NextEpisodeIcon />
              </button>
            )}
            {t && t.kind === 'series' && (
              <button className={`pl-btn ${panel === 'episodes' ? 'on' : ''}`} aria-label="Episodes" onClick={() => setPanel((p) => (p === 'episodes' ? null : 'episodes'))}>
                <EpisodesIcon />
              </button>
            )}
            <button className={`pl-btn ${panel === 'audio' ? 'on' : ''}`} aria-label="Audio & Subtitles" onClick={() => setPanel((p) => (p === 'audio' ? null : 'audio'))}>
              <Icon name="subtitles" size={40} />
            </button>
            <button className="pl-btn" aria-label={fs ? 'Exit full screen' : 'Full screen'} onClick={toggleFs}>
              {fs ? <ExitFullscreenIcon /> : <FullscreenIcon />}
            </button>
          </div>
        </div>
      </div>

      {panel === 'episodes' && t && (
        <div className="pl-panel episodes-panel">
          <h3>{t.name}</h3>
          <div className="pl-ep-list">
            {episodes.map((e) => (
              <button key={e.id} className={`pl-ep ${episode && e.id === episode.id ? 'on' : ''}`} onClick={() => goEpisode(e)}>
                <span className="pl-ep-n">S{e.season}:E{e.number}</span>
                <span className="pl-ep-name">{e.name}</span>
                <span className="pl-ep-d">{clipLength(e.duration)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      {panel === 'audio' && t && (
        <div className="pl-panel audio-panel">
          <div>
            <h3>Audio</h3>
            <div className="pl-opt on"><Icon name="check" size={18} /> {languageName(t.language)} [Original]</div>
          </div>
          <div>
            <h3>Subtitles</h3>
            <div className="pl-opt on"><Icon name="check" size={18} /> Off</div>
            <p className="muted small">No subtitle tracks are available for this clip.</p>
          </div>
        </div>
      )}
    </div>
  )
}
