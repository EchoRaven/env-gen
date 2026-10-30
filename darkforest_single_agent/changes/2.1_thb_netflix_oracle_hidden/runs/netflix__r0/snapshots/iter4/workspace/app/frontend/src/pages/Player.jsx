import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Icon from '../components/Icon';
import { API } from '../api';
import { fmtClock, rememberClipLength } from '../utils';

function SkipIcon({ dir }) {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d={dir < 0 ? 'M12 4a8 8 0 1 1-7.4 5' : 'M12 4a8 8 0 1 0 7.4 5'}
        stroke="currentColor" strokeWidth="1.8" fill="none"
      />
      <path d={dir < 0 ? 'M12 1v6L8 4z' : 'M12 1v6l4-3z'} fill="currentColor" />
      <text x="12" y="15.5" textAnchor="middle" fontSize="7" fontWeight="700" fill="currentColor" fontFamily="Inter, Arial">10</text>
    </svg>
  );
}

function NextIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M5 4.5v15l11-7.5z" strokeLinejoin="round" />
      <path d="M19.5 4v16" />
    </svg>
  );
}

function EpisodesIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="2" y="10" width="15" height="10" rx="1.5" />
      <path d="M5 7h14.5a1.5 1.5 0 0 1 1.5 1.5V16" />
      <path d="M8 4h13.5A1.5 1.5 0 0 1 23 5.5" />
    </svg>
  );
}

function FullscreenIcon({ on }) {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      {on
        ? <path d="M8 3v5H3M16 3v5h5M8 21v-5H3M16 21v-5h5" />
        : <path d="M3 8V3h5M21 8V3h-5M3 16v5h5M21 16v5h-5" />}
    </svg>
  );
}

export default function Player() {
  const { titleId } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const epParam = params.get('ep');
  const videoRef = useRef(null);
  const shellRef = useRef(null);
  const hideTimer = useRef(null);
  const lastSaved = useRef(0);
  const resumeAt = useRef(0);

  const [title, setTitle] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [error, setError] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [panel, setPanel] = useState(null); // 'episodes' | 'subtitles' | 'volume' | null
  const [isFull, setIsFull] = useState(false);
  const [nextTitle, setNextTitle] = useState(null);
  const [hoverPct, setHoverPct] = useState(null);
  const [flash, setFlash] = useState(null); // transient center indicator
  const [playError, setPlayError] = useState(null);
  const flashTimer = useRef(null);
  const showFlash = useCallback((txt) => { setFlash({ txt, k: Date.now() }); clearTimeout(flashTimer.current); flashTimer.current = setTimeout(() => setFlash(null), 700); }, []);

  useEffect(() => {
    let alive = true;
    setTitle(null); setError(null); setEpisodes([]);
    API.title(titleId).then((t) => {
      if (!alive) return;
      setTitle(t);
      resumeAt.current = t.progress_seconds || 0;
      if (t.kind === 'series') API.episodes(titleId).then((e) => alive && setEpisodes(e)).catch(() => {});
      else API.titles({ genre: t.genre, limit: 6 }).then((r) => alive && setNextTitle(r.find((x) => x.id !== t.id) || null)).catch(() => {});
    }).catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [titleId]);

  const episode = episodes.length
    ? episodes.find((e) => String(e.id) === epParam) || episodes.find((e) => e.id === title?.resume_episode_id) || episodes[0]
    : null;
  const epIndex = episode ? episodes.indexOf(episode) : -1;
  const nextEpisode = epIndex >= 0 ? episodes[epIndex + 1] : null;

  const save = useCallback((force = false) => {
    const v = videoRef.current;
    if (!v || !title) return;
    const now = Date.now();
    if (!force && now - lastSaved.current < 4000) return;
    lastSaved.current = now;
    API.saveProgress({ title_id: title.id, progress_seconds: Math.floor(v.currentTime), episode_id: episode ? episode.id : undefined }).catch(() => {});
  }, [title, episode]);

  // Persist progress on leave.
  useEffect(() => () => save(true), [save]);

  const poke = useCallback(() => {
    setShowControls(true);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => { if (videoRef.current && !videoRef.current.paused) setShowControls(false); }, 3000);
  }, []);
  useEffect(() => () => clearTimeout(hideTimer.current), []);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      showFlash('▶');
      v.play().then(() => setPlayError(null)).catch((err) => setPlayError(err?.name === 'NotSupportedError' ? 'This browser can’t play this clip format (H.264/MP4).' : 'Playback could not start. Press play to try again.'));
    } else { v.pause(); showFlash('❚❚'); }
  }, [showFlash]);
  const seekBy = useCallback((d) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.max(0, Math.min((v.duration || 0), v.currentTime + d));
    setTime(v.currentTime);
    showFlash(d < 0 ? `« ${Math.abs(d)}s` : `${d}s »`);
    poke();
  }, [poke, showFlash]);
  const toggleMute = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
  }, []);
  const toggleFull = useCallback(() => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else shellRef.current?.requestFullscreen?.().catch(() => {});
  }, []);
  const back = useCallback(() => {
    save(true);
    if (location.key !== 'default') navigate(-1); else navigate('/browse');
  }, [navigate, location.key, save]);
  const goNext = useCallback(() => {
    save(true);
    if (nextEpisode) { resumeAt.current = 0; setParams({ ep: String(nextEpisode.id) }, { replace: true }); }
    else if (nextTitle) navigate(`/watch/${nextTitle.id}`, { replace: true });
  }, [nextEpisode, nextTitle, navigate, setParams, save]);

  useEffect(() => {
    const onFs = () => setIsFull(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onFs);
    return () => document.removeEventListener('fullscreenchange', onFs);
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT') return;
      if (e.key === ' ' || e.key === 'k') { e.preventDefault(); togglePlay(); }
      else if (e.key === 'ArrowLeft') seekBy(-10);
      else if (e.key === 'ArrowRight') seekBy(10);
      else if (e.key === 'm') toggleMute();
      else if (e.key === 'f') toggleFull();
      else if (e.key === 'Escape' && !document.fullscreenElement) back();
      poke();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [togglePlay, seekBy, toggleMute, toggleFull, back, poke]);

  const onLoaded = () => {
    const v = videoRef.current;
    setDuration(v.duration);
    rememberClipLength(title?.video_url, v.duration);
    if (resumeAt.current > 0 && resumeAt.current < v.duration - 1) v.currentTime = resumeAt.current;
    resumeAt.current = 0;
    v.volume = volume;
    v.play().catch(() => { v.muted = true; setMuted(true); v.play().catch(() => {}); });
  };

  const seekTo = (e) => {
    const v = videoRef.current;
    if (!v || !duration) return;
    const r = e.currentTarget.getBoundingClientRect();
    v.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * duration;
    save(true);
  };

  if (error) {
    return (
      <div className="player error">
        <button className="pl-back" aria-label="Back" onClick={back}><Icon name="nf-arrow_left" size={40} /></button>
        <p>{error}</p>
      </div>
    );
  }

  const pct = duration ? (time / duration) * 100 : 0;
  return (
    <div className={`player ${showControls || !playing ? 'show' : 'hide'} ${!playing && title ? 'paused' : ''}`} ref={shellRef} onMouseMove={poke} data-testid="player">
      {title && (
        <video
          ref={videoRef}
          key={`${title.id}-${episode?.id || 0}`}
          src={title.video_url}
          poster={title.backdrop}
          onLoadedMetadata={onLoaded}
          onTimeUpdate={(e) => { setTime(e.currentTarget.currentTime); save(); }}
          onProgress={(e) => { const b = e.currentTarget.buffered; if (b.length) setBuffered(b.end(b.length - 1)); }}
          onPlay={() => { setPlaying(true); poke(); }}
          onPause={() => { setPlaying(false); setShowControls(true); save(true); }}
          onEnded={() => { setPlaying(false); save(true); }}
          onVolumeChange={(e) => { setMuted(e.currentTarget.muted); setVolume(e.currentTarget.volume); }}
          onClick={togglePlay}
          onError={() => setPlayError('This clip could not be loaded in this browser (H.264/MP4).')}
          onPlaying={() => setPlayError(null)}
          playsInline
        />
      )}
      {!title && <div className="pl-loading"><div className="spinner" /></div>}
      {flash && <div className="pl-flash" key={flash.k}>{flash.txt}</div>}
      {playError && <div className="pl-error" role="alert">{playError}</div>}

      <div className="pl-top">
        <button className="pl-btn" aria-label="Back to browse" onClick={back}><Icon name="nf-arrow_left" size={40} /></button>
      </div>

      {!playing && title && (
        <div className="pl-paused-info" onClick={togglePlay}>
          <span className="muted">You're watching</span>
          <h2>{title.name}</h2>
          {episode && <h3>Season {episode.season}: Ep. {episode.number} “{episode.name}”</h3>}
          <p>{title.synopsis}</p>
        </div>
      )}

      <div className="pl-bottom" onClick={(e) => e.stopPropagation()}>
        <div className="pl-timeline">
          <div
            className="pl-track"
            role="slider"
            tabIndex={0}
            aria-label="Seek"
            aria-valuemin={0}
            aria-valuemax={Math.floor(duration)}
            aria-valuenow={Math.floor(time)}
            onClick={seekTo}
            onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHoverPct((e.clientX - r.left) / r.width); }}
            onMouseLeave={() => setHoverPct(null)}
          >
            <div className="pl-buffer" style={{ width: `${duration ? (buffered / duration) * 100 : 0}%` }} />
            <div className="pl-played" style={{ width: `${pct}%` }} />
            <div className="pl-knob" style={{ left: `${pct}%` }} />
            {hoverPct != null && duration > 0 && (
              <div className="pl-hover-time" style={{ left: `${hoverPct * 100}%` }}>{fmtClock(hoverPct * duration)}</div>
            )}
          </div>
          <span className="pl-remaining">{fmtClock(Math.max(0, duration - time))}</span>
        </div>
        <div className="pl-controls">
          <div className="pl-left">
            <button className="pl-btn" aria-label={playing ? 'Pause' : 'Play'} onClick={togglePlay}>
              {playing ? <Icon name="pause" size={40} className="filled" /> : <Icon name="nf-play" size={40} />}
            </button>
            <button className="pl-btn" aria-label="Rewind 10 seconds" onClick={() => seekBy(-10)}><SkipIcon dir={-1} /></button>
            <button className="pl-btn" aria-label="Forward 10 seconds" onClick={() => seekBy(10)}><SkipIcon dir={1} /></button>
            <div className="pl-volume" onMouseLeave={() => setPanel((p) => (p === 'volume' ? null : p))}>
              {panel === 'volume' && (
                <div className="pl-volume-pop">
                  <input
                    type="range" min="0" max="1" step="0.05" aria-label="Volume"
                    value={muted ? 0 : volume}
                    onChange={(e) => { const v = videoRef.current; v.volume = Number(e.target.value); v.muted = v.volume === 0; }}
                  />
                </div>
              )}
              <button className="pl-btn" aria-label={muted ? 'Unmute' : 'Mute'} onClick={toggleMute} onMouseEnter={() => setPanel('volume')}>
                <Icon name={muted || volume === 0 ? 'nf-volume_off' : 'nf-volume_high'} size={40} />
              </button>
            </div>
          </div>
          <div className="pl-title">
            {title && <><b>{title.name}</b>{episode && <> <span>E{episode.number}</span> <span className="pl-ep">{episode.name}</span></>}</>}
          </div>
          <div className="pl-right">
            {(nextEpisode || nextTitle) && (
              <button className="pl-btn" aria-label={nextEpisode ? 'Next episode' : 'Next title'} title={nextEpisode ? `Next: ${nextEpisode.name}` : `Next: ${nextTitle.name}`} onClick={goNext}>
                <NextIcon />
              </button>
            )}
            {episodes.length > 0 && (
              <button className="pl-btn" aria-label="Episodes" onClick={() => setPanel((p) => (p === 'episodes' ? null : 'episodes'))}><EpisodesIcon /></button>
            )}
            <button className="pl-btn" aria-label="Audio and subtitles" onClick={() => setPanel((p) => (p === 'subtitles' ? null : 'subtitles'))}>
              <Icon name="nf-subtitles" size={40} />
            </button>
            <button className="pl-btn" aria-label={isFull ? 'Exit full screen' : 'Full screen'} onClick={toggleFull}><FullscreenIcon on={isFull} /></button>
          </div>
        </div>

        {panel === 'episodes' && (
          <div className="pl-panel episodes-panel">
            <h3>{title.name} · Season {episode?.season}</h3>
            <ul>
              {episodes.filter((e) => e.season === episode?.season).map((e) => (
                <li key={e.id}>
                  <button className={e.id === episode?.id ? 'current' : ''} onClick={() => { save(true); resumeAt.current = 0; setParams({ ep: String(e.id) }, { replace: true }); setPanel(null); }}>
                    <span className="n">{e.number}</span>
                    <span className="nm">{e.name}</span>
                    <span className="d">{e.duration}m</span>
                  </button>
                </li>
              ))}
            </ul>
            {[...new Set(episodes.map((e) => e.season))].length > 1 && (
              <div className="season-tabs">
                {[...new Set(episodes.map((e) => e.season))].map((s) => (
                  <button key={s} className={s === episode?.season ? 'on' : ''} onClick={() => { const first = episodes.find((e) => e.season === s); resumeAt.current = 0; setParams({ ep: String(first.id) }, { replace: true }); }}>Season {s}</button>
                ))}
              </div>
            )}
          </div>
        )}
        {panel === 'subtitles' && (
          <div className="pl-panel subs-panel">
            <div>
              <h3>Audio</h3>
              <div className="opt on">✓ Original{title?.language ? ` (${title.language.toUpperCase()})` : ''}</div>
            </div>
            <div>
              <h3>Subtitles</h3>
              <div className="opt on">✓ Off</div>
              <p className="muted small">No subtitle tracks are available for this clip.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
