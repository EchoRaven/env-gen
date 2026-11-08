import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, assetUrl } from '../api'
import { useApp } from '../context'
import Icon from '../components/Icon'
import { LoadingPage, ErrorState } from '../components/PageUtilities'

const languageNames = { en: 'English', ja: 'Japanese', zh: 'Chinese', ko: 'Korean', af: 'Afrikaans', es: 'Spanish', ru: 'Russian', hi: 'Hindi', de: 'German' }

function clock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

export default function Player() {
  const { titleId } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { profile } = useApp()
  const wrapRef = useRef(null)
  const videoRef = useRef(null)
  const hideTimer = useRef(null)
  const saveTimer = useRef(null)
  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(0)
  const [current, setCurrent] = useState(0)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [showEpisodes, setShowEpisodes] = useState(false)
  const [showTracks, setShowTracks] = useState(false)
  const [trackTab, setTrackTab] = useState('subtitles')
  const [subtitles, setSubtitles] = useState(false)
  const [buffering, setBuffering] = useState(true)

  const episodeId = Number(params.get('episode')) || null
  const currentEpisode = useMemo(
    () => episodes.find(item => Number(item.id) === episodeId) || null,
    [episodes, episodeId],
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([api(`/api/titles/${titleId}`), api(`/api/titles/${titleId}/episodes`)])
      .then(([detail, eps]) => {
        if (cancelled) return
        setTitle(detail)
        setEpisodes(eps)
      }).catch(err => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [titleId])

  const saveProgress = useCallback((seconds = videoRef.current?.currentTime || 0, useBeacon = false) => {
    if (!title || !seconds) return
    const clipDuration = videoRef.current?.duration
    const storedSeconds = Number.isFinite(clipDuration) && clipDuration > 0
      ? Math.floor((seconds / clipDuration) * Math.max(1, title.duration))
      : Math.floor(seconds)
    const body = JSON.stringify({ title_id: title.id, progress_seconds: storedSeconds, episode_id: episodeId })
    const token = localStorage.getItem('netflix_access_token')
    const profileId = localStorage.getItem('netflix_profile_id')
    if (useBeacon) {
      // sendBeacon cannot set auth headers, so use a keepalive authenticated request.
      fetch('/api/continue-watching', {
        method: 'POST', keepalive: true,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'X-Profile-Id': profileId || '' },
        body,
      }).catch(() => {})
    } else {
      api('/api/continue-watching', { method: 'POST', body: { title_id: title.id, progress_seconds: storedSeconds, episode_id: episodeId } }).catch(() => {})
    }
  }, [title, episodeId])

  useEffect(() => {
    if (!title) return
    saveTimer.current = setInterval(() => {
      const video = videoRef.current
      if (video && !video.paused && video.currentTime > 1) saveProgress(video.currentTime)
    }, 5000)
    return () => {
      clearInterval(saveTimer.current)
      saveProgress(videoRef.current?.currentTime || 1)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title?.id, saveProgress])

  useEffect(() => {
    const beforeUnload = () => saveProgress(videoRef.current?.currentTime || 0, true)
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [saveProgress])

  const revealControls = useCallback(() => {
    setControlsVisible(true)
    clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(() => {
      if (videoRef.current && !videoRef.current.paused && !showEpisodes && !showTracks) {
        setControlsVisible(false)
      }
    }, 3200)
  }, [showEpisodes, showTracks])

  useEffect(() => {
    revealControls()
    return () => clearTimeout(hideTimer.current)
  }, [revealControls, playing])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      video.play().catch(() => setPlaying(false))
    } else {
      video.pause()
    }
    revealControls()
  }, [revealControls])

  const seekBy = (amount) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.max(0, Math.min(video.duration || duration, video.currentTime + amount))
    revealControls()
  }

  const nextEpisode = useCallback(() => {
    if (!episodes.length) return
    let index = episodes.findIndex(item => item.id === episodeId)
    if (index < 0) index = -1
    const next = episodes[index + 1]
    if (next) {
      const nextParams = new URLSearchParams(params)
      nextParams.set('episode', String(next.id))
      setParams(nextParams)
      saveProgress(videoRef.current?.currentTime || 0)
      setTimeout(() => {
        videoRef.current?.load()
        videoRef.current?.play().catch(() => {})
      }, 100)
    }
  }, [episodes, episodeId, params, setParams, saveProgress])

  const chooseEpisode = (episode) => {
    const nextParams = new URLSearchParams(params)
    nextParams.set('episode', String(episode.id))
    setParams(nextParams)
    setShowEpisodes(false)
    setTimeout(() => videoRef.current?.play().catch(() => {}), 120)
  }

  useEffect(() => {
    const onKey = (event) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return
      if (event.code === 'Space') { event.preventDefault(); togglePlay() }
      else if (event.key === 'ArrowLeft') seekBy(-10)
      else if (event.key === 'ArrowRight') seekBy(10)
      else if (event.key.toLowerCase() === 'm') toggleMute()
      else if (event.key.toLowerCase() === 'f') toggleFullscreen()
      else if (event.key === 'Escape' && (showEpisodes || showTracks)) { setShowEpisodes(false); setShowTracks(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [togglePlay, showEpisodes, showTracks])

  const toggleMute = () => {
    const video = videoRef.current
    if (!video) return
    video.muted = !video.muted
    setMuted(video.muted)
    revealControls()
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

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) wrapRef.current?.requestFullscreen?.().catch(() => {})
    else document.exitFullscreen?.()
  }

  const back = () => {
    saveProgress(videoRef.current?.currentTime || 0)
    if (window.history.length > 1) navigate(-1)
    else navigate('/browse')
  }

  if (loading) return <div className="player-page"><LoadingPage label="Starting playback…" /></div>
  if (error || !title) return <div className="player-page"><ErrorState message={error || 'This title is unavailable.'} onRetry={() => window.location.reload()} /></div>

  const videoUrl = assetUrl(currentEpisode?.video_url || title.video_url || 'assets/video/clip_18972999.webm')
  const episodeIndex = episodes.findIndex(item => item.id === episodeId)
  const next = episodeIndex >= 0 ? episodes[episodeIndex + 1] : episodes[0]

  return (
    <div
      ref={wrapRef}
      className={`player-page ${controlsVisible ? 'controls-visible' : 'controls-hidden'}`}
      onMouseMove={revealControls}
      onMouseLeave={() => { if (playing && !showEpisodes && !showTracks) setControlsVisible(false) }}
    >
      <video
        ref={videoRef}
        className="player-video"
        src={videoUrl}
        poster={assetUrl(title.backdrop || title.poster)}
        autoPlay
        playsInline
        onClick={togglePlay}
        onPlay={() => { setPlaying(true); setBuffering(false); revealControls() }}
        onPause={() => { setPlaying(false); setControlsVisible(true) }}
        onWaiting={() => setBuffering(true)}
        onCanPlay={() => setBuffering(false)}
        onLoadedMetadata={event => {
          const video = event.currentTarget
          setDuration(video.duration || 0)
          video.volume = volume
          if (title.progress_seconds > 0 && title.duration > 0) {
            const fraction = Math.min(0.92, title.progress_seconds / title.duration)
            video.currentTime = fraction * (video.duration || 0)
          }
          video.play().catch(() => {
            // Browsers block audible autoplay without a direct gesture. Start muted so
            // playback remains real, and the visible volume control can restore sound.
            video.muted = true
            setMuted(true)
            video.play().catch(() => setPlaying(false))
          })
        }}
        onTimeUpdate={event => setCurrent(event.currentTarget.currentTime)}
        onEnded={() => {
          if (next) nextEpisode()
          else { setPlaying(false); setControlsVisible(true) }
        }}
      />

      <div className="player-top-gradient" />
      <div className="player-topbar">
        <button className="player-back" onClick={back} aria-label="Go back"><Icon name="back" size={34} /></button>
        <div className="player-title-copy">
          <span>{title.kind === 'series' ? `S${currentEpisode?.season || 1}:E${currentEpisode?.number || 1}` : 'Film'}</span>
          <strong>{title.name}</strong>
          {currentEpisode && <em>{currentEpisode.name}</em>}
        </div>
        <div className="player-profile"><span>{profile?.name || 'Profile'}</span></div>
      </div>

      {buffering && <div className="player-buffering"><span className="spinner large" /></div>}
      {subtitles && (
        <div className="player-caption-notice">No subtitle track is supplied for this clip.</div>
      )}

      <div className="player-controls" onClick={event => event.stopPropagation()}>
        <div className="player-seek-row">
          <span>{clock(current)}</span>
          <input
            className="seek-range"
            type="range"
            min="0"
            max={duration || 0}
            step="0.1"
            value={Math.min(current, duration || 0)}
            onChange={event => {
              const nextTime = Number(event.target.value)
              if (videoRef.current) videoRef.current.currentTime = nextTime
              setCurrent(nextTime)
            }}
            aria-label="Seek"
            style={{ '--seek-percent': `${duration ? (current / duration) * 100 : 0}%` }}
          />
          <span>{clock(duration)}</span>
        </div>
        <div className="player-control-row">
          <div className="player-control-left">
            <button onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}><Icon name={playing ? 'pause' : 'play'} size={32} /></button>
            <button onClick={() => seekBy(-10)} aria-label="Rewind 10 seconds" className="seek-ten"><Icon name="refresh" size={30} /><b>10</b></button>
            <button onClick={() => seekBy(10)} aria-label="Forward 10 seconds" className="seek-ten forward"><Icon name="refresh" size={30} /><b>10</b></button>
            <div className="volume-control">
              <button onClick={toggleMute} aria-label={muted ? 'Unmute' : 'Mute'}><Icon name={muted || volume === 0 ? 'mute' : 'volume'} size={29} /></button>
              <input type="range" min="0" max="1" step="0.05" value={muted ? 0 : volume} onChange={changeVolume} aria-label="Volume" />
            </div>
            {episodes.length > 0 && (
              <button onClick={nextEpisode} aria-label="Next episode" disabled={!next} className="next-episode"><Icon name="new-episode" size={30} /></button>
            )}
          </div>
          <div className="player-control-right">
            {episodes.length > 0 && (
              <button onClick={() => { setShowEpisodes(value => !value); setShowTracks(false); revealControls() }} aria-label="Episodes" className={showEpisodes ? 'active' : ''}>
                <Icon name="new-episode" size={28} />
              </button>
            )}
            <button onClick={() => { setShowTracks(value => !value); setShowEpisodes(false); revealControls() }} aria-label="Subtitles and audio" className={showTracks ? 'active' : ''}>
              <Icon name="subtitles" size={28} />
            </button>
            <button onClick={toggleFullscreen} aria-label="Full screen"><Icon name="fullscreen" size={28} /></button>
          </div>
        </div>
      </div>

      {showEpisodes && (
        <aside className="player-panel episodes-panel">
          <div className="player-panel-head"><h2>Episodes</h2><button onClick={() => setShowEpisodes(false)} aria-label="Close episodes"><Icon name="close" size={24} /></button></div>
          <div className="player-episode-list">
            {episodes.map((episode, index) => (
              <button key={episode.id} className={`player-episode ${episode.id === episodeId ? 'active' : ''}`} onClick={() => chooseEpisode(episode)}>
                <span className="player-episode-number">{index + 1}</span>
                <img src={assetUrl(episode.thumbnail || title.backdrop)} alt="" />
                <span className="player-episode-copy"><strong>{episode.name}</strong><span>{episode.duration_label}</span><em>{episode.synopsis}</em></span>
              </button>
            ))}
          </div>
        </aside>
      )}

      {showTracks && (
        <aside className="player-panel tracks-panel">
          <div className="player-panel-head"><h2>Audio &amp; Subtitles</h2><button onClick={() => setShowTracks(false)} aria-label="Close audio and subtitles"><Icon name="close" size={24} /></button></div>
          <div className="track-tabs">
            <button className={trackTab === 'subtitles' ? 'active' : ''} onClick={() => setTrackTab('subtitles')}>Subtitles</button>
            <button className={trackTab === 'audio' ? 'active' : ''} onClick={() => setTrackTab('audio')}>Audio</button>
          </div>
          {trackTab === 'subtitles' && (
            <div className="track-options">
              <button className={!subtitles ? 'selected' : ''} onClick={() => setSubtitles(false)}>Off<span>{!subtitles ? '✓' : ''}</span></button>
              <button className={subtitles ? 'selected' : ''} onClick={() => setSubtitles(true)}>English<span>{subtitles ? '✓' : ''}</span></button>
              <p>No subtitle file is included with the supplied trailer clips.</p>
            </div>
          )}
          {trackTab === 'audio' && (
            <div className="track-options">
              <button className="selected" onClick={toggleMute}>{languageNames[title.language] || 'Original'} — Original<span>✓</span></button>
              <button disabled>Audio description — not supplied<span>—</span></button>
              <p>Only the clip&apos;s original audio track is available.</p>
            </div>
          )}
        </aside>
      )}
    </div>
  )
}
