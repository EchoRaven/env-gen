import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import api from '../api'
import Icon from '../components/Icon'
import Spinner from '../components/Spinner'
import { useAuth } from '../context/AuthContext'

function formatTime(value) {
  if (!Number.isFinite(value)) return '0:00'
  const total = Math.max(0, Math.floor(value))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}` : `${minutes}:${String(seconds).padStart(2, '0')}`
}

export default function WatchPage() {
  const { titleId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { profile } = useAuth()
  const videoRef = useRef(null)
  const hideTimer = useRef(null)
  const saveTimer = useRef(null)
  const progressRef = useRef(0)
  const resumeApplied = useRef(false)

  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [episode, setEpisode] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(1)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [episodesOpen, setEpisodesOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(null)
  const [ended, setEnded] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const [titleData, episodeData] = await Promise.all([
          api.get(`/api/titles/${titleId}`),
          api.get(`/api/titles/${titleId}/episodes`),
        ])
        if (!active) return
        setTitle(titleData.item)
        const rows = episodeData.items || []
        setEpisodes(rows)
        const requested = Number(searchParams.get('episode'))
        const selected = rows.find((row) => row.id === requested) || rows[0] || null
        setEpisode(selected)
      } catch (err) {
        if (active) setError(err.message)
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [titleId]) // eslint-disable-line react-hooks/exhaustive-deps

  const saveProgress = useCallback((force = false) => {
    const player = videoRef.current
    if (!player || !title) return
    const value = Math.floor(player.currentTime || 0)
    if (!force && Math.abs(value - progressRef.current) < 5) return
    progressRef.current = value
    api.post('/api/continue-watching', { title_id: title.id, progress_seconds: value }).catch(() => {})
  }, [title])

  useEffect(() => {
    if (!playing) return undefined
    saveTimer.current = setInterval(() => saveProgress(false), 10000)
    return () => clearInterval(saveTimer.current)
  }, [playing, saveProgress])

  useEffect(() => {
    const flush = () => saveProgress(true)
    window.addEventListener('beforeunload', flush)
    return () => {
      window.removeEventListener('beforeunload', flush)
      flush()
    }
  }, [saveProgress])

  useEffect(() => {
    if (!videoRef.current || resumeApplied.current || !duration) return
    const player = videoRef.current
    const resume = Number(title?.progress_seconds || 0)
    if (resume > 2 && resume < duration - 2) {
      player.currentTime = resume
      setCurrentTime(resume)
    }
    resumeApplied.current = true
  }, [title, duration])

  const pokeControls = useCallback(() => {
    setControlsVisible(true)
    clearTimeout(hideTimer.current)
    if (playing && !episodesOpen && !settingsOpen && !ended) {
      hideTimer.current = setTimeout(() => setControlsVisible(false), 3200)
    }
  }, [playing, episodesOpen, settingsOpen, ended])

  useEffect(() => {
    pokeControls()
    return () => clearTimeout(hideTimer.current)
  }, [pokeControls])

  useEffect(() => {
    const onFullscreen = () => setFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', onFullscreen)
    return () => document.removeEventListener('fullscreenchange', onFullscreen)
  }, [])

  const togglePlay = useCallback(() => {
    const player = videoRef.current
    if (!player) return
    if (player.paused) {
      setEnded(false)
      player.play().catch(() => setPlaying(false))
    } else {
      player.pause()
    }
    pokeControls()
  }, [pokeControls])

  const skip = (seconds) => {
    const player = videoRef.current
    if (!player) return
    player.currentTime = Math.max(0, Math.min(player.duration || 0, player.currentTime + seconds))
    pokeControls()
  }

  const toggleMute = () => {
    const player = videoRef.current
    if (!player) return
    const next = !player.muted
    player.muted = next
    setMuted(next)
    if (!next && !player.volume) {
      player.volume = 1
      setVolume(1)
    }
  }

  const changeVolume = (event) => {
    const value = Number(event.target.value)
    if (videoRef.current) {
      videoRef.current.volume = value
      videoRef.current.muted = value === 0
    }
    setVolume(value)
    setMuted(value === 0)
  }

  const seek = (event) => {
    const value = Number(event.target.value)
    if (videoRef.current) videoRef.current.currentTime = value
    setCurrentTime(value)
  }

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen()
      else await document.documentElement.requestFullscreen()
    } catch { /* fullscreen can be blocked by the browser */ }
  }

  const nextEpisode = useCallback(() => {
    if (!episodes.length) return
    const index = episodes.findIndex((row) => row.id === episode?.id)
    const next = episodes[index + 1]
    if (!next) return
    setEpisode(next)
    setEnded(false)
    if (videoRef.current) {
      videoRef.current.currentTime = 0
      videoRef.current.play().catch(() => {})
    }
  }, [episodes, episode])

  useEffect(() => {
    const onKey = (event) => {
      if (event.target.tagName === 'INPUT' || event.target.tagName === 'SELECT') return
      if (event.key === ' ' || event.key === 'k') { event.preventDefault(); togglePlay() }
      else if (event.key === 'ArrowLeft') skip(-10)
      else if (event.key === 'ArrowRight') skip(10)
      else if (event.key.toLowerCase() === 'm') toggleMute()
      else if (event.key.toLowerCase() === 'f') toggleFullscreen()
      else if (event.key === 'Escape') {
        if (settingsOpen) setSettingsOpen(null)
        else if (episodesOpen) setEpisodesOpen(false)
        else if (document.fullscreenElement) document.exitFullscreen()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const next = useMemo(() => {
    const index = episodes.findIndex((row) => row.id === episode?.id)
    return index >= 0 ? episodes[index + 1] : null
  }, [episodes, episode])

  const back = () => {
    saveProgress(true)
    if (window.history.length > 1) navigate(-1)
    else navigate('/browse')
  }

  if (loading) return <div className="player-loading"><Spinner label="Preparing your stream…" /></div>
  if (error) return <div className="player-loading"><p>{error}</p><button className="btn btn-light" onClick={back}>Go back</button></div>
  if (!title) return null

  const progressPercent = duration ? (currentTime / duration) * 100 : 0
  const episodeLabel = episode ? `S${episode.season}:E${episode.number} “${episode.name}”` : null

  return (
    <div className={`watch-page ${controlsVisible ? 'controls-visible' : 'controls-hidden'}`} onMouseMove={pokeControls} onClick={pokeControls}>
      <video
        ref={videoRef}
        className="watch-video"
        src={title.video_url}
        playsInline
        muted={muted}
        autoPlay
        onClick={togglePlay}
        onPlay={() => { setPlaying(true); setEnded(false) }}
        onPause={() => { setPlaying(false); saveProgress(true) }}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
        onDurationChange={(event) => setDuration(event.currentTarget.duration)}
        onEnded={() => { setPlaying(false); setEnded(true); setControlsVisible(true); saveProgress(true) }}
      />

      <div className="player-top player-overlay">
        <button className="player-back" onClick={back} aria-label="Back to browse"><Icon name="chevronLeft" size={30} /></button>
        <div className="player-title-copy">
          <strong>{title.name}</strong>
          {episodeLabel ? <span>{episodeLabel}</span> : <span>{title.year} · {title.maturity_rating}</span>}
        </div>
        <div className="player-profile"><span>{profile?.name}</span></div>
      </div>

      {!playing && !ended ? (
        <button className="center-play" onClick={togglePlay} aria-label="Play video"><Icon name="play" size={58} /></button>
      ) : null}

      {ended ? (
        <div className="end-screen">
          <span className="page-kicker">UP NEXT</span>
          <h2>{next ? next.name : title.name}</h2>
          <p>{next ? next.synopsis : 'You’ve reached the end of this trailer.'}</p>
          <div className="end-actions">
            <button className="btn btn-play" onClick={() => { if (videoRef.current) { videoRef.current.currentTime = 0; videoRef.current.play() } }}><Icon name="refresh" size={20} /> Replay</button>
            {next ? <button className="btn btn-light" onClick={nextEpisode}><Icon name="play" size={20} /> Next Episode</button> : null}
            <button className="btn btn-more" onClick={back}>Back to Browse</button>
          </div>
        </div>
      ) : null}

      <div className="player-controls player-overlay" onClick={(event) => event.stopPropagation()}>
        <div className="seek-row">
          <input
            className="seek-slider"
            type="range"
            min="0"
            max={duration || 0}
            step="0.1"
            value={Math.min(currentTime, duration || 0)}
            onChange={seek}
            style={{ '--seek': `${progressPercent}%` }}
            aria-label="Seek video"
          />
        </div>
        <div className="control-row">
          <div className="control-left">
            <button className="player-icon" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}><Icon name={playing ? 'pause' : 'play'} size={28} /></button>
            <button className="player-icon" onClick={() => skip(-10)} aria-label="Back 10 seconds"><span className="skip-icon">10</span><Icon name="refresh" size={22} className="skip-back" /></button>
            <button className="player-icon" onClick={() => skip(10)} aria-label="Forward 10 seconds"><span className="skip-icon">10</span><Icon name="refresh" size={22} className="skip-forward" /></button>
            <div className="volume-group">
              <button className="player-icon" onClick={toggleMute} aria-label={muted ? 'Unmute' : 'Mute'}><Icon name={muted ? 'volumeOff' : 'volume'} size={24} /></button>
              <input type="range" min="0" max="1" step="0.05" value={muted ? 0 : volume} onChange={changeVolume} aria-label="Volume" />
            </div>
            <span className="time-display">{formatTime(currentTime)} <span>/</span> {formatTime(duration)}</span>
          </div>
          <div className="control-right">
            {episodes.length ? <button className="control-text" onClick={() => setEpisodesOpen((open) => !open)}>Episodes</button> : null}
            {next ? <button className="player-icon next-episode" onClick={nextEpisode} aria-label="Next episode"><Icon name="play" size={22} /><span className="next-bar" /></button> : null}
            <button className="player-icon" onClick={() => setSettingsOpen('subtitles')} aria-label="Subtitles"><Icon name="subtitles" size={23} /></button>
            <button className="player-icon" onClick={() => setSettingsOpen('audio')} aria-label="Audio settings"><Icon name="audio" size={24} /></button>
            <button className="player-icon" onClick={toggleFullscreen} aria-label={fullscreen ? 'Exit full screen' : 'Enter full screen'}><Icon name="fullscreen" size={24} /></button>
          </div>
        </div>
      </div>

      {episodesOpen ? (
        <aside className="player-panel episode-panel" onClick={(event) => event.stopPropagation()}>
          <div className="player-panel-head"><h2>Episodes</h2><button className="icon-btn" onClick={() => setEpisodesOpen(false)} aria-label="Close episodes"><Icon name="close" size={22} /></button></div>
          <div className="player-episode-list">
            {episodes.map((row) => (
              <button key={row.id} className={`player-episode ${row.id === episode?.id ? 'current' : ''}`} onClick={() => { setEpisode(row); setEnded(false); if (videoRef.current) { videoRef.current.currentTime = 0; videoRef.current.play().catch(() => {}) } setEpisodesOpen(false) }}>
                <img src={row.thumbnail} alt="" />
                <span><strong>S{row.season}:E{row.number} {row.name}</strong><small>{row.synopsis}</small></span>
                <Icon name="play" size={20} />
              </button>
            ))}
          </div>
        </aside>
      ) : null}

      {settingsOpen ? (
        <section className="player-panel settings-panel" onClick={(event) => event.stopPropagation()}>
          <div className="player-panel-head"><h2>{settingsOpen === 'subtitles' ? 'Subtitles' : 'Audio'}</h2><button className="icon-btn" onClick={() => setSettingsOpen(null)} aria-label="Close settings"><Icon name="close" size={22} /></button></div>
          {settingsOpen === 'subtitles' ? (
            <div className="settings-empty">
              <p>No subtitle tracks are available for this trailer.</p>
              <button className="btn btn-outline btn-small" onClick={() => setSettingsOpen(null)}>Off</button>
            </div>
          ) : (
            <div className="settings-empty">
              <p>English · Stereo</p>
              <span>The provided clips include one audio track.</span>
              <button className="btn btn-outline btn-small" onClick={() => setSettingsOpen(null)}>Done</button>
            </div>
          )}
        </section>
      ) : null}
    </div>
  )
}
