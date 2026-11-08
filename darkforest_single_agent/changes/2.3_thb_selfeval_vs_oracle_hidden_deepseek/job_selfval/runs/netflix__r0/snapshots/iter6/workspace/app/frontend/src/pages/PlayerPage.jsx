import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import Icon from '../components/Icon.jsx'

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function PlayerPage() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { api, activeProfile } = useAuth()
  const videoRef = useRef(null)
  const shellRef = useRef(null)
  const hideTimer = useRef(null)
  const savedRef = useRef(0)
  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(1)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [buffered, setBuffered] = useState(0)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [settingsMenu, setSettingsMenu] = useState('')
  const [episodesOpen, setEpisodesOpen] = useState(false)
  const [started, setStarted] = useState(false)

  const episodeId = params.get('ep')
  const episode = episodes.find((entry) => String(entry.id) === String(episodeId)) || episodes[0] || null

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([api.get(`/api/titles/${id}`), api.get(`/api/titles/${id}/episodes`), api.get('/api/continue-watching')])
      .then(([titleResult, episodeResult, progressResult]) => {
        if (cancelled) return
        setTitle(titleResult.item)
        const nextEpisodes = episodeResult.items || []
        setEpisodes(nextEpisodes)
        if (nextEpisodes.length && !params.get('ep')) {
          const nextParams = new URLSearchParams(params)
          nextParams.set('ep', String(nextEpisodes[0].id))
          setParams(nextParams, { replace: true })
        }
        const saved = (progressResult.items || []).find((item) => item.id === titleResult.item.id)
        if (saved?.progress_seconds) savedRef.current = saved.progress_seconds
      })
      .catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [api, id]) // eslint-disable-line react-hooks/exhaustive-deps

  const saveProgress = useCallback((clipSeconds) => {
    if (!title || !Number.isFinite(clipSeconds) || clipSeconds < 0.5) return
    const clipDuration = videoRef.current?.duration || 0
    const catalogDuration = title.duration || clipDuration || 1
    const progressSeconds = clipDuration > 0
      ? Math.floor((clipSeconds / clipDuration) * catalogDuration)
      : Math.floor(clipSeconds)
    if (Math.abs(progressSeconds - savedRef.current) < 30 && progressSeconds !== Math.floor(catalogDuration)) return
    savedRef.current = progressSeconds
    api.post('/api/continue-watching', { title_id: title.id, progress_seconds: progressSeconds }).catch(() => {})
  }, [api, title])

  useEffect(() => {
    const interval = setInterval(() => {
      if (videoRef.current && !videoRef.current.paused) saveProgress(videoRef.current.currentTime)
    }, 15000)
    return () => clearInterval(interval)
  }, [saveProgress])

  useEffect(() => () => {
    if (videoRef.current) saveProgress(videoRef.current.currentTime)
  }, [saveProgress])

  useEffect(() => {
    saveProgress(currentTime)
  }, [currentTime, saveProgress])

  useEffect(() => {
    function onKey(event) {
      if (event.target.tagName === 'INPUT' || event.target.tagName === 'SELECT') return
      const video = videoRef.current
      if (!video) return
      if (event.code === 'Space') { event.preventDefault(); togglePlay() }
      else if (event.key === 'ArrowRight') { event.preventDefault(); skip(10) }
      else if (event.key === 'ArrowLeft') { event.preventDefault(); skip(-10) }
      else if (event.key.toLowerCase() === 'm') { toggleMute() }
      else if (event.key.toLowerCase() === 'f') { toggleFullscreen() }
      else if (event.key === 'Escape') { navigate(-1) }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }) // eslint-disable-line react-hooks/exhaustive-deps

  function wakeControls() {
    setControlsVisible(true)
    clearTimeout(hideTimer.current)
    if (!videoRef.current?.paused) {
      hideTimer.current = setTimeout(() => {
        setControlsVisible(false)
        setSettingsMenu('')
      }, 3200)
    }
  }

  useEffect(() => {
    wakeControls()
    return () => clearTimeout(hideTimer.current)
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps

  async function togglePlay() {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      try { await video.play(); setStarted(true) } catch { setError('Playback was blocked by the browser. Press play again.') }
    } else {
      video.pause()
      saveProgress(video.currentTime)
    }
    wakeControls()
  }

  function skip(seconds) {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.max(0, Math.min(video.duration || 0, video.currentTime + seconds))
    wakeControls()
  }

  function seek(event) {
    const video = videoRef.current
    const value = Number(event.target.value)
    if (video) video.currentTime = value
    setCurrentTime(value)
  }

  function toggleMute() {
    const video = videoRef.current
    if (!video) return
    video.muted = !video.muted
    setMuted(video.muted)
  }

  function changeVolume(event) {
    const video = videoRef.current
    const value = Number(event.target.value)
    if (!video) return
    video.volume = value
    video.muted = value === 0
    setVolume(value)
    setMuted(value === 0)
  }

  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) await shellRef.current?.requestFullscreen()
      else await document.exitFullscreen()
    } catch {
      setError('Fullscreen is not available in this browser.')
    }
  }

  function nextEpisode() {
    if (!episode) return
    const index = episodes.findIndex((entry) => entry.id === episode.id)
    const next = episodes[index + 1]
    if (!next) return
    const nextParams = new URLSearchParams(params)
    nextParams.set('ep', String(next.id))
    setParams(nextParams)
    if (videoRef.current) {
      videoRef.current.currentTime = 0
      videoRef.current.play().catch(() => {})
    }
    setCurrentTime(0)
    savedRef.current = 0
    setEpisodesOpen(false)
  }

  function chooseEpisode(entry) {
    const nextParams = new URLSearchParams(params)
    nextParams.set('ep', String(entry.id))
    setParams(nextParams)
    if (videoRef.current) {
      videoRef.current.currentTime = 0
      videoRef.current.play().catch(() => {})
    }
    setCurrentTime(0)
    savedRef.current = 0
    setEpisodesOpen(false)
  }

  function onLoadedMetadata() {
    const video = videoRef.current
    if (!video) return
    setDuration(video.duration || 0)
    if (savedRef.current > 0) {
      const catalogDuration = title?.duration || video.duration || 1
      const resumeAt = (savedRef.current / catalogDuration) * (video.duration || 0)
      if (resumeAt > 0.5 && resumeAt < (video.duration || 0) - 0.5) video.currentTime = resumeAt
    }
    video.play().then(() => setStarted(true)).catch(() => {})
  }

  function onTimeUpdate() {
    const video = videoRef.current
    if (!video) return
    setCurrentTime(video.currentTime)
    if (video.buffered.length) {
      try { setBuffered(video.buffered.end(video.buffered.length - 1)) } catch { /* noop */ }
    }
  }

  const nextAvailable = episode && episodes.findIndex((entry) => entry.id === episode.id) < episodes.length - 1
  const displayName = episode && title?.kind === 'series' ? `${episode.name}` : title?.name

  function goBack() {
    if (window.history.length > 1) navigate(-1)
    else navigate('/browse')
  }

  return (
    <div
      className={`player-shell ${controlsVisible ? 'controls-visible' : ''}`}
      ref={shellRef}
      onMouseMove={wakeControls}
      onTouchStart={wakeControls}
      onClick={(event) => { if (event.target === event.currentTarget || event.target.classList.contains('player-video')) { togglePlay(); wakeControls() } }}
    >
      <video
        ref={videoRef}
        className="player-video"
        src={title?.video_url || ''}
        poster={title?.backdrop || title?.poster || ''}
        muted={muted}
        playsInline
        onLoadedMetadata={onLoadedMetadata}
        onTimeUpdate={onTimeUpdate}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => { setPlaying(false); saveProgress(videoRef.current?.currentTime || 0) }}
        onError={() => setError('The trailer clip could not be loaded.')}
      />
      <div className="player-vignette top" />
      <div className="player-vignette bottom" />

      <header className="player-top">
        <button type="button" className="player-icon-button back-button" onClick={goBack} aria-label="Back"><Icon name="chevron-left" size={34} /></button>
        <div className="player-title-block">
          <span className="player-brand">NETFLIX</span>
          <strong>{title?.name || 'Loading…'}</strong>
          {episode && title?.kind === 'series' && <small>Season {episode.season}: Episode {episode.number} · {episode.name}</small>}
        </div>
        <button type="button" className="player-profile-button" onClick={() => navigate('/profiles')} aria-label="Switch profile">
          <img src={activeProfile?.avatar || '/assets/avatars/avatar_1.svg'} alt="" />
        </button>
      </header>

      {!started && !loading && !error && (
        <button type="button" className="player-big-play" onClick={togglePlay} aria-label="Play video"><Icon name="play" size={48} /></button>
      )}
      {loading && <div className="player-loading">Loading player…</div>}
      {error && <div className="player-error">{error}</div>}

      <div className="player-bottom" onClick={(event) => event.stopPropagation()}>
        <div className="player-timeline-wrap">
          <input
            className="player-timeline"
            type="range"
            min="0"
            max={duration || 0}
            step="0.1"
            value={Math.min(currentTime, duration || 0)}
            onChange={seek}
            aria-label="Seek"
            style={{ '--played': `${duration ? (currentTime / duration) * 100 : 0}%`, '--buffered': `${duration ? (buffered / duration) * 100 : 0}%` }}
          />
        </div>
        <div className="player-controls">
          <div className="player-controls-left">
            <button type="button" className="player-icon-button" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}><Icon name={playing ? 'pause' : 'play'} size={28} /></button>
            <button type="button" className="player-icon-button skip-button" onClick={() => skip(-10)} aria-label="Rewind 10 seconds"><span className="skip-glyph">10</span><Icon name="chevron-left" size={24} /></button>
            <button type="button" className="player-icon-button skip-button" onClick={() => skip(10)} aria-label="Forward 10 seconds"><Icon name="chevron-right" size={24} /><span className="skip-glyph">10</span></button>
            <div className="volume-control">
              <button type="button" className="player-icon-button" onClick={toggleMute} aria-label={muted ? 'Unmute' : 'Mute'}><Icon name={muted || volume === 0 ? 'volume-x' : 'volume-2'} size={25} /></button>
              <input type="range" min="0" max="1" step="0.05" value={muted ? 0 : volume} onChange={changeVolume} aria-label="Volume" />
            </div>
            <span className="player-time">{formatTime(currentTime)} / {formatTime(duration)}</span>
          </div>
          <div className="player-controls-right">
            {title?.kind === 'series' && (
              <button type="button" className="player-icon-button" onClick={nextEpisode} aria-label="Next episode" disabled={!nextAvailable} title={nextAvailable ? 'Next episode' : 'No next episode'}><span className="next-glyph">▶|</span></button>
            )}
            <button type="button" className="player-icon-button" onClick={() => { setSettingsMenu(settingsMenu === 'subtitles' ? '' : 'subtitles'); setEpisodesOpen(false) }} aria-label="Subtitles"><span className="cc-glyph">CC</span></button>
            <button type="button" className="player-icon-button" onClick={() => { setSettingsMenu(settingsMenu === 'audio' ? '' : 'audio'); setEpisodesOpen(false) }} aria-label="Audio"><Icon name="volume-2" size={24} /></button>
            {episodes.length > 0 && <button type="button" className="player-icon-button" onClick={() => { setEpisodesOpen((open) => !open); setSettingsMenu('') }} aria-label="Episodes"><Icon name="info" size={24} /></button>}
            <button type="button" className="player-icon-button" onClick={toggleFullscreen} aria-label="Fullscreen"><Icon name="maximize" size={24} /></button>
          </div>
        </div>

        {settingsMenu && (
          <div className="player-popover">
            {settingsMenu === 'subtitles' ? (
              <>
                <h3>Subtitles</h3>
                <button type="button" className="menu-choice selected" onClick={() => setSettingsMenu('')}><span className="menu-radio" /> Off</button>
                <p className="menu-empty">No subtitle tracks are included with the provided trailer clips.</p>
              </>
            ) : (
              <>
                <h3>Audio</h3>
                <button type="button" className="menu-choice selected" onClick={() => setSettingsMenu('')}><span className="menu-radio" /> English — original audio</button>
                <p className="menu-empty">This clip contains one audio track.</p>
              </>
            )}
          </div>
        )}
      </div>

      <aside className={`episode-drawer ${episodesOpen ? 'open' : ''}`}>
        <div className="episode-drawer-header">
          <h2>Episodes</h2>
          <button type="button" className="player-icon-button" onClick={() => setEpisodesOpen(false)} aria-label="Close episodes"><Icon name="x" size={22} /></button>
        </div>
        <div className="episode-drawer-list">
          {episodes.map((entry) => (
            <button type="button" key={entry.id} className={`drawer-episode ${episode?.id === entry.id ? 'active' : ''}`} onClick={() => chooseEpisode(entry)}>
              <img src={entry.thumbnail || title?.backdrop} alt="" />
              <span><small>S{entry.season}:E{entry.number}</small><strong>{entry.name}</strong><em>{Math.round((entry.duration || 0) / 60)}m</em></span>
              <Icon name="play" size={18} />
            </button>
          ))}
        </div>
      </aside>
      {!episodesOpen && episodes.length > 0 && (
        <div className="player-now-playing">
          <span>Now playing</span>
          <strong>{displayName}</strong>
        </div>
      )}
    </div>
  )
}
