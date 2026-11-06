import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon'
import { mediaUrl, fmtClock, fmtDuration } from '../lib/util'

export default function Player({ title, episodes, startEpisodeId, onBack, saveProgress, resumeFrom }) {
  const videoRef = useRef(null)
  const rootRef = useRef(null)
  const hideTimer = useRef(null)
  const lastSave = useRef(0)
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [menu, setMenu] = useState(null) // 'subs' | 'audio' | null
  const [subs, setSubs] = useState('English (Auto)')
  const [audioLang, setAudioLang] = useState('English')
  const [epOpen, setEpOpen] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [started, setStarted] = useState(false)
  const [canPlay, setCanPlay] = useState(false)

  const [epIndex, setEpIndex] = useState(() => {
    if (!episodes || !episodes.length) return -1
    if (startEpisodeId) {
      const i = episodes.findIndex((e) => e.id === startEpisodeId)
      if (i >= 0) return i
    }
    return 0
  })
  const ep = epIndex >= 0 ? episodes[epIndex] : null

  const wake = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(() => {
      hideTimer.current = null
      if (videoRef.current && !videoRef.current.paused) setUiHidden(true)
    }, 3000)
  }, [])

  const [uiHidden, setUiHidden] = useState(false)
  useEffect(() => {
    const onMove = () => { setUiHidden(false); wake() }
    document.addEventListener('mousemove', onMove)
    return () => { document.removeEventListener('mousemove', onMove); if (hideTimer.current) clearTimeout(hideTimer.current) }
  }, [wake])

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.volume = volume
    v.muted = muted
  }, [volume, muted])

  const seekTo = (t) => {
    const v = videoRef.current
    if (!v || !isFinite(v.duration) || v.duration === 0) return
    v.currentTime = Math.max(0, Math.min(v.duration, t))
    setCurrent(v.currentTime)
  }

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) { v.play().catch(() => {}); } else { v.pause() }
  }, [])

  useEffect(() => {
    const onKey = (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA')) return
      const v = videoRef.current
      if (!v) return
      if (e.code === 'Space' || e.code === 'KeyK') { e.preventDefault(); togglePlay() }
      else if (e.code === 'ArrowLeft') seekBy(-10)
      else if (e.code === 'ArrowRight') seekBy(10)
      else if (e.code === 'KeyM') setMuted((m) => !m)
      else if (e.code === 'KeyF') toggleFullscreen()
      else if (e.code === 'Escape') { setMenu(null); setEpOpen(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const seekBy = (d) => { const v = videoRef.current; if (v) seekTo(v.currentTime + d) }

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      rootRef.current?.requestFullscreen?.().then(() => setFullscreen(true)).catch(() => {})
    } else {
      document.exitFullscreen?.().catch(() => {})
    }
  }
  useEffect(() => {
    const onFs = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  // resume from continue-watching on first loadedmetadata
  const resumed = useRef(false)
  const onLoadedMetadata = () => {
    const v = videoRef.current
    if (!v) return
    setCanPlay(true)
    if (resumed.current) return
    resumed.current = true
    if (resumeFrom > 5 && resumeFrom < v.duration - 5) v.currentTime = resumeFrom
    v.play().catch(() => {})
  }

  const onTimeUpdate = () => {
    const v = videoRef.current
    if (!v) return
    setCurrent(v.currentTime)
    if (saveProgress && v.currentTime > 0) {
      const now = Date.now()
      if (now - lastSave.current > 5000 || v.currentTime / v.duration > 0.95) {
        lastSave.current = now
        saveProgress(title.id, v.currentTime)
      }
    }
  }

  const onEnded = () => {
    if (saveProgress) saveProgress(title.id, duration || 0)
    if (ep && epIndex < episodes.length - 1) setEpIndex(epIndex + 1)
  }

  const pct = duration > 0 ? (current / duration) * 100 : 0
  const seekPct = (clientX, el) => {
    const r = el.getBoundingClientRect()
    const p = (clientX - r.left) / r.width
    seekTo(p * (duration || 0))
  }

  const epList = episodes || []
  const canNext = ep && epIndex < epList.length - 1

  return (
    <div
      className="player-root"
      ref={rootRef}
      onMouseMove={() => { setUiHidden(false); wake() }}
    >
      <video
        ref={videoRef}
        src={mediaUrl(title.video_url)}
        poster={mediaUrl(title.backdrop || title.poster)}
        onLoadedMetadata={onLoadedMetadata}
        onTimeUpdate={onTimeUpdate}
        onPlay={() => { setPlaying(true); setStarted(true); wake() }}
        onPause={() => { setPlaying(false); setUiHidden(false) }}
        onEnded={onEnded}
        onDurationChange={() => setDuration(videoRef.current?.duration || 0)}
        onClick={togglePlay}
      />
      <div className={`player-overlay ${uiHidden && playing ? 'hidden' : ''}`}>
        <button className={`player-back ${uiHidden ? 'hidden' : ''}`} aria-label="Back" onClick={onBack}>
          <Icon name="arrow_left" size={36} />
        </button>
        {canPlay && !playing && (
          <button className="player-bigplay" aria-label="Play" onClick={togglePlay}>
            <Icon name="play" size={44} />
          </button>
        )}
        {started && (
          <div className="player-title">
            {title.name}{ep ? <span style={{ color: '#a3a3a3', fontWeight: 400 }}> — S{ep.season}:E{ep.number} {ep.name}</span> : ''}
          </div>
        )}
      </div>
      <div className={`player-controls ${uiHidden && playing ? 'hidden' : ''}`}>
        <div className="seek-row">
          <div className="seek-fill" onPointerDown={(e) => seekPct(e.clientX, e.currentTarget)} ref={(el) => { if (el) el.style.setProperty('--w', `${pct}%`) }}>
            <div style={{ width: `${pct}%` }} />
          </div>
          <span className="time-text">{fmtClock(current)} / {fmtClock(duration)}</span>
        </div>
        <div className="player-btn-row">
          <button className="pbtn" aria-label={playing ? 'Pause' : 'Play'} onClick={togglePlay}>
            <Icon name={playing ? 'pause' : 'play'} size={30} />
          </button>
          <button className="pbtn" aria-label="Rewind 10 seconds" onClick={() => seekBy(-10)}>
            <svg viewBox="0 0 24 24" width={28} height={28} fill="none" aria-hidden="true">
              <path fill="currentColor" d="M12 5V1L7 6l5 5V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z" />
              <text x="10" y="17.5" fontSize="8" fill="currentColor" stroke="none">10</text>
            </svg>
          </button>
          <button className="pbtn" aria-label="Forward 10 seconds" onClick={() => seekBy(10)}>
            <svg viewBox="0 0 24 24" width={28} height={28} fill="none" aria-hidden="true">
              <path fill="currentColor" d="M12 5V1l5 5-5 5V7a6 6 0 1 0 6 6h2a8 8 0 1 1-8-8z" />
              <text x="9" y="17.5" fontSize="8" fill="currentColor" stroke="none">10</text>
            </svg>
          </button>
          <div className="vol-wrap">
            <button className="pbtn" aria-label={muted ? 'Unmute' : 'Mute'} onClick={() => setMuted((m) => !m)}>
              <Icon name={muted || volume === 0 ? 'volume_off' : 'volume_high'} size={26} />
            </button>
            <input
              className="vol"
              type="range" min="0" max="1" step="0.05"
              value={muted ? 0 : volume}
              aria-label="Volume"
              onChange={(e) => { setVolume(parseFloat(e.target.value)); setMuted(parseFloat(e.target.value) === 0) }}
            />
          </div>
          <div className="player-right">
            {canNext && (
              <button className="pbtn" style={{ position: 'static' }} title="Next episode" aria-label="Next episode" onClick={() => setEpIndex(epIndex + 1)}>
                <svg viewBox="0 0 24 24" width={28} height={28} fill="none" aria-hidden="true">
                  <path fill="currentColor" d="M8 5v14l11-7z" />
                  <rect x="17.5" y="5" width="2.5" height="14" fill="currentColor" />
                </svg>
              </button>
            )}
            <div style={{ position: 'relative' }}>
              <button className="pbtn" aria-label="Subtitles and audio" onClick={() => setMenu(menu === 'subs' ? null : 'subs')}>
                <Icon name="subtitles" size={26} />
              </button>
              {menu === 'subs' && (
                <div className="player-menu">
                  <div className="player-menu-title">Subtitles</div>
                  {['Off', 'English (Auto)', 'Spanish (Auto)'].map((o) => (
                    <button key={o} className={`player-menu-item ${subs === o ? 'selected' : ''}`} onClick={() => { setSubs(o); setMenu(null) }}>{o}</button>
                  ))}
                </div>
              )}
            </div>
            <div style={{ position: 'relative' }}>
              <button className="pbtn" aria-label="Audio options" onClick={() => setMenu(menu === 'audio' ? null : 'audio')}>
                <Icon name="audio" size={26} />
              </button>
              {menu === 'audio' && (
                <div className="player-menu">
                  <div className="player-menu-title">Audio</div>
                  {['English', 'Spanish'].map((o) => (
                    <button key={o} className={`player-menu-item ${audioLang === o ? 'selected' : ''}`} onClick={() => { setAudioLang(o); setMenu(null) }}>{o}</button>
                  ))}
                </div>
              )}
            </div>
            {epList.length > 0 && (
              <button className="pbtn" aria-label="Episodes" onClick={() => setEpOpen(!epOpen)}>
                <Icon name="list" size={26} />
              </button>
            )}
            <button className="pbtn" aria-label="Toggle fullscreen" onClick={toggleFullscreen}>
              <svg viewBox="0 0 24 24" width={26} height={26} fill="none" aria-hidden="true">
                <path fill="currentColor" d={fullscreen
                  ? 'M5 5h6v2H7v4H5V5zm14 0v6h-2V7h-4V5h6zM5 19v-6h2v4h4v2H5zm14 0h-6v-2h4v-4h2v6z'
                  : 'M4 4h6v2H6v4H4V4zm16 0v6h-2V6h-4V4h6zM4 20v-6h2v4h4v2H4zm16 0h-6v-2h4v-4h2v6z'} />
              </svg>
            </button>
          </div>
        </div>
      </div>
      {epOpen && epList.length > 0 && (
        <div className="ep-drawer">
          <h3>Episodes</h3>
          {epList.map((e2, i) => (
            <div
              key={e2.id}
              style={{
                display: 'grid', gridTemplateColumns: '140px 22px 1fr', gap: 12, alignItems: 'center',
                padding: '12px 8px', cursor: 'pointer', borderRadius: 4,
                background: i === epIndex ? 'rgba(229,9,20,0.15)' : 'transparent',
              }}
              onClick={() => { setEpIndex(i); setEpOpen(false); const v = videoRef.current; if (v) { v.currentTime = 0 } }}
            >
              <div className="ep-thumb" style={{ width: 140 }}>
                <img src={mediaUrl(e2.thumbnail || title.backdrop || title.poster)} alt="" loading="lazy" />
              </div>
              <div className="ep-num">{e2.number}</div>
              <div>
                <div style={{ fontSize: 0.9, marginBottom: 4 }}>{e2.name}</div>
                <div style={{ fontSize: 0.75, color: '#a3a3a3' }}>{fmtDuration(e2.duration)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
