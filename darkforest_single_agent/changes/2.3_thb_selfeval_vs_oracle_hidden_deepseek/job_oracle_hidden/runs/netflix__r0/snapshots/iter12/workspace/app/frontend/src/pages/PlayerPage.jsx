import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { AssetIcon } from '../icons'
import { formatClock, languageName } from '../utils'

export default function PlayerPage() {
  const { titleId } = useParams()
  const { authFetch } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const playerRef = useRef(null)
  const videoRef = useRef(null)
  const hideTimer = useRef(null)
  const progressRef = useRef(0)
  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [episode, setEpisode] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(true)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [panel, setPanel] = useState(null)
  const [captionsNote, setCaptionsNote] = useState('')
  const [videoError, setVideoError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const detail = await authFetch(`/api/titles/${titleId}`)
        if (cancelled) return
        setTitle(detail)
        if (detail.kind === 'series') {
          const list = await authFetch(`/api/titles/${titleId}/episodes`)
          if (cancelled) return
          setEpisodes(list)
          const requested = Number(searchParams.get('episode'))
          setEpisode(list.find((item) => item.id === requested) || list[0] || null)
        }
      } catch (requestError) {
        if (!cancelled) setError(requestError.message || 'This title could not be loaded.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [authFetch, titleId, searchParams])

  const saveProgress = useCallback(
    async (seconds) => {
      if (!title || !Number.isFinite(seconds) || seconds < 1) return
      try {
        await authFetch('/api/continue-watching', {
          method: 'POST',
          body: { title_id: title.id, progress_seconds: Math.round(seconds) },
        })
      } catch {
        // Progress persistence is best-effort while playback continues.
      }
    },
    [authFetch, title],
  )

  useEffect(() => {
    progressRef.current = currentTime
  }, [currentTime])

  useEffect(() => {
    if (!title) return undefined
    const interval = window.setInterval(() => saveProgress(progressRef.current), 7000)
    return () => {
      window.clearInterval(interval)
      saveProgress(progressRef.current)
    }
  }, [title, saveProgress])

  useEffect(() => {
    const onKey = (event) => {
      const video = videoRef.current
      if (!video) return
      if (event.code === 'Space' && !['INPUT', 'BUTTON', 'SELECT'].includes(document.activeElement?.tagName)) {
        event.preventDefault()
        togglePlay()
      }
      if (event.key === 'ArrowLeft') seekBy(-10)
      if (event.key === 'ArrowRight') seekBy(10)
      if (event.key === 'f') toggleFullscreen()
      if (event.key === 'm') toggleMute()
      if (event.key === 'Escape') setPanel(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  const showControls = () => {
    setControlsVisible(true)
    window.clearTimeout(hideTimer.current)
    hideTimer.current = window.setTimeout(() => {
      if (!videoRef.current?.paused) setControlsVisible(false)
    }, 3200)
  }

  const togglePlay = () => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      video.play().catch(() => setVideoError('Playback could not start. Press play again.'))
    } else {
      video.pause()
      saveProgress(video.currentTime)
    }
    showControls()
  }

  const seekBy = (amount) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.min(video.duration || 0, Math.max(0, video.currentTime + amount))
    showControls()
  }

  const toggleMute = () => {
    const video = videoRef.current
    if (!video) return
    video.muted = !video.muted
    setMuted(video.muted)
    if (!video.muted && video.volume === 0) {
      video.volume = 1
      setVolume(1)
    }
  }

  const changeVolume = (event) => {
    const next = Number(event.target.value)
    const video = videoRef.current
    if (!video) return
    video.volume = next
    video.muted = next === 0
    setVolume(next)
    setMuted(next === 0)
  }

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) await playerRef.current?.requestFullscreen()
      else await document.exitFullscreen()
    } catch {
      setVideoError('Fullscreen is not available in this browser.')
    }
  }

  const currentEpisodeIndex = episodes.findIndex((item) => item.id === episode?.id)
  const nextEpisode = currentEpisodeIndex >= 0 ? episodes[currentEpisodeIndex + 1] : null

  const playNextEpisode = () => {
    if (!nextEpisode) return
    setEpisode(nextEpisode)
    setSearchParams({ episode: String(nextEpisode.id) }, { replace: true })
    const video = videoRef.current
    if (video) {
      video.currentTime = 0
      video.play().catch(() => {})
    }
  }

  const back = () => {
    saveProgress(progressRef.current)
    if (window.history.length > 1) navigate(-1)
    else navigate(`/title/${titleId}`)
  }

  if (loading) {
    return <div className="player-loading"><span className="loading-ring" /><p>Loading player…</p></div>
  }
  if (error) {
    return (
      <div className="player-loading">
        <h1>Unable to play this title</h1>
        <p>{error}</p>
        <button className="button button-white" onClick={() => navigate('/browse')}>Back to browse</button>
      </div>
    )
  }

  const video = videoRef.current
  const seekPercent = duration ? (currentTime / duration) * 100 : 0
  const displayTitle = episode
    ? `${title.name} · S${episode.season}:E${episode.number} ${episode.name}`
    : title.name

  return (
    <div
      className={`player-page ${controlsVisible ? 'controls-visible' : 'controls-hidden'}`}
      ref={playerRef}
      onMouseMove={showControls}
      onClick={() => {
        if (!controlsVisible) showControls()
      }}
    >
      <video
        ref={videoRef}
        className="player-video"
        src={title.video_url}
        poster={title.backdrop || title.poster}
        autoPlay
        muted
        playsInline
        preload="auto"
        onClick={(event) => {
          event.stopPropagation()
          togglePlay()
        }}
        onPlay={() => { setPlaying(true); showControls() }}
        onPause={() => { setPlaying(false); setControlsVisible(true) }}
        onLoadedMetadata={(event) => {
          setDuration(event.currentTarget.duration || 0)
          event.currentTarget.volume = volume
          event.currentTarget.muted = muted
        }}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onEnded={() => {
          setPlaying(false)
          setControlsVisible(true)
          saveProgress(duration || progressRef.current)
          if (nextEpisode) playNextEpisode()
        }}
        onError={() => setVideoError('The trailer clip could not be played.')}
      />

      <div className="player-vignette" aria-hidden="true" />
      <div className="player-topbar">
        <button className="player-back" onClick={back} aria-label="Go back">
          <AssetIcon name="arrow_left" size={30} />
        </button>
        <div className="player-title-overlay">
          <span className="player-title-name">{displayTitle}</span>
          {episode ? <span className="player-episode-copy">{episode.synopsis}</span> : null}
        </div>
      </div>

      {!playing && !videoError ? (
        <button className="player-center-play" onClick={togglePlay} aria-label="Play video">
          <AssetIcon name="play" size={54} />
        </button>
      ) : null}
      {videoError ? <div className="player-error-banner">{videoError}</div> : null}
      {captionsNote ? <div className="player-captions-note">{captionsNote}</div> : null}

      <div className="player-controls">
        <input
          className="seek-bar"
          type="range"
          min="0"
          max={duration || 0}
          step="0.1"
          value={Math.min(currentTime, duration || 0)}
          onChange={(event) => {
            const value = Number(event.target.value)
            if (videoRef.current) videoRef.current.currentTime = value
            setCurrentTime(value)
          }}
          style={{ '--seek-progress': `${seekPercent}%` }}
          aria-label="Seek"
        />
        <div className="player-control-row">
          <div className="player-controls-left">
            <button className="player-icon-button" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}>
              <AssetIcon name={playing ? 'pause' : 'play'} size={30} />
            </button>
            <button className="player-icon-button seek-button" onClick={() => seekBy(-10)} aria-label="Rewind 10 seconds">
              <AssetIcon name="arrow_left" size={26} />
              <span>10</span>
            </button>
            <button className="player-icon-button seek-button" onClick={() => seekBy(10)} aria-label="Forward 10 seconds">
              <AssetIcon name="arrow_left" size={26} className="forward-icon" />
              <span>10</span>
            </button>
            {nextEpisode ? (
              <button className="player-icon-button" onClick={playNextEpisode} aria-label="Play next episode">
                <AssetIcon name="new_episode" size={28} />
              </button>
            ) : null}
            <div className="volume-control">
              <button className="player-icon-button" onClick={toggleMute} aria-label={muted ? 'Unmute' : 'Mute'}>
                <AssetIcon name={muted || volume === 0 ? 'volume_off' : 'volume_high'} size={28} />
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={muted ? 0 : volume}
                onChange={changeVolume}
                aria-label="Volume"
              />
            </div>
            <span className="player-time">{formatClock(currentTime)} / {formatClock(duration)}</span>
          </div>
          <div className="player-controls-right">
            <button className="player-chip-button" onClick={() => setPanel(panel === 'episodes' ? null : 'episodes')} aria-label="Episodes">
              <AssetIcon name="play" size={18} />
              <span>Episodes</span>
              {episode ? <small>S{episode.season}:E{episode.number}</small> : null}
            </button>
            <button className="player-icon-button" onClick={() => setPanel(panel === 'subtitles' ? null : 'subtitles')} aria-label="Subtitles">
              <AssetIcon name="subtitles" size={28} />
            </button>
            <button className="player-icon-button" onClick={() => setPanel(panel === 'audio' ? null : 'audio')} aria-label="Audio settings">
              <AssetIcon name="audio_description" size={28} />
            </button>
            <button className="player-icon-button" onClick={toggleFullscreen} aria-label="Fullscreen">
              <span className="fullscreen-glyph" aria-hidden="true">⛶</span>
            </button>
          </div>
        </div>
      </div>

      {panel ? (
        <div className="player-side-panel" onClick={(event) => event.stopPropagation()}>
          <div className="player-panel-header">
            <h2>{panel === 'episodes' ? 'Episodes' : panel === 'subtitles' ? 'Subtitles' : 'Audio'}</h2>
            <button className="player-icon-button" onClick={() => setPanel(null)} aria-label="Close panel">
              <AssetIcon name="close" size={24} />
            </button>
          </div>
          {panel === 'episodes' ? (
            episodes.length ? episodes.map((item) => (
              <button
                className={`player-panel-episode ${item.id === episode?.id ? 'active' : ''}`}
                key={item.id}
                onClick={() => {
                  setEpisode(item)
                  setSearchParams({ episode: String(item.id) }, { replace: true })
                  if (videoRef.current) {
                    videoRef.current.currentTime = 0
                    videoRef.current.play().catch(() => {})
                  }
                  setPanel(null)
                }}
              >
                <img src={item.thumbnail} alt="" />
                <span>
                  <strong>{item.number}. {item.name}</strong>
                  <small>Season {item.season} · {item.duration}m</small>
                </span>
              </button>
            )) : <p className="player-panel-empty">This title has no episodes.</p>
          ) : panel === 'audio' ? (
            <div className="player-panel-options">
              <button className="player-panel-option active" onClick={() => setPanel(null)}>
                <span>{languageName(title.language)}</span>
                <small>Original audio</small>
              </button>
              <p className="player-panel-empty">No other audio tracks are included with the supplied trailer.</p>
            </div>
          ) : (
            <div className="player-panel-options">
              <button
                className="player-panel-option active"
                onClick={() => {
                  setCaptionsNote('')
                  setPanel(null)
                }}
              >
                <span>Off</span>
              </button>
              <button
                className="player-panel-option"
                onClick={() => {
                  setCaptionsNote('Subtitles are not included with the supplied trailer clip.')
                  setPanel(null)
                }}
              >
                <span>English</span>
                <small>Unavailable for this clip</small>
              </button>
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
