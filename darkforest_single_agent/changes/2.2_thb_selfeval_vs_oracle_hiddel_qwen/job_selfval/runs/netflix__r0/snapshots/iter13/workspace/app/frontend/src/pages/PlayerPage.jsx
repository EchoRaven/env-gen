import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return h
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

/* ---- custom line-art player icons (match the reference player) ---- */
function IconBack({ size = "w-[1.7vw]" }) {
  return (
    <svg viewBox="0 0 34 32" className={size} fill="none" aria-hidden="true">
      <path d="M30 16H7" stroke="white" strokeWidth="5" strokeLinecap="round" />
      <path d="M15 5L4 16l11 11" stroke="white" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}
function IconPause({ size = "w-[1.7vw]" }) {
  return (
    <svg viewBox="0 0 32 36" className={size} aria-hidden="true">
      <rect x="3" y="0" width="10" height="36" rx="2" fill="white" />
      <rect x="19" y="0" width="10" height="36" rx="2" fill="white" />
    </svg>
  );
}
function IconPlay({ size = "w-[1.7vw]" }) {
  return (
    <svg viewBox="0 0 32 36" className={size} aria-hidden="true">
      <path d="M4 2l24 16L4 34V2z" fill="white" />
    </svg>
  );
}
function IconRewind({ size = "w-[2.5vw]", flip = false }) {
  return (
    <svg viewBox="0 0 48 48" className={size} fill="none" style={flip ? { transform: "scaleX(-1)" } : undefined} aria-hidden="true">
      <path d="M40.5 14.5A19 19 0 1 0 43 24" stroke="white" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M40 4l6.5 10.5L29 12.5" fill="white" />
    </svg>
  );
}
function IconVolume({ muted, size = "w-[2.6vw]" }) {
  return (
    <svg viewBox="0 0 48 48" className={size} fill="none" aria-hidden="true">
      <rect x="1" y="17" width="11" height="14" fill="white" />
      <path d="M12 17l12-7v28l-12-7v-14z" fill="white" />
      {muted ? (
        <path d="M30 20l12 8M42 20l-12 8" stroke="white" strokeWidth="4" strokeLinecap="round" />
      ) : (
        <>
          <path d="M30 20a7 7 0 0 1 0 8" stroke="white" strokeWidth="4" strokeLinecap="round" />
          <path d="M36 15a13 13 0 0 1 0 18" stroke="white" strokeWidth="4" strokeLinecap="round" />
          <path d="M42 10a19 19 0 0 1 0 28" stroke="white" strokeWidth="4" strokeLinecap="round" />
        </>
      )}
    </svg>
  );
}
function IconCC({ size = "w-[2.1vw]" }) {
  return (
    <svg viewBox="0 0 44 36" className={size} fill="none" aria-hidden="true">
      <path d="M31 8a13 13 0 0 0-22 9 13 13 0 0 0 22 9" stroke="white" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M38 4v28" stroke="white" strokeWidth="4.5" strokeLinecap="round" />
    </svg>
  );
}
function IconAudio({ size = "w-[2.4vw]" }) {
  return (
    <svg viewBox="0 0 48 42" className={size} fill="none" aria-hidden="true">
      <path d="M18 3h26" stroke="white" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M44 7v13" stroke="white" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M16 15h22" stroke="white" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M18 17v9" stroke="white" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M4 23h22" stroke="white" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M4 25v13" stroke="white" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M22 25v13" stroke="white" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M4 38h24" stroke="white" strokeWidth="3.5" strokeLinecap="round" />
    </svg>
  );
}
function IconEpisodes({ size = "w-[2.4vw]" }) {
  return (
    <svg viewBox="0 0 48 42" className={size} fill="none" aria-hidden="true">
      <path d="M4 6v28" stroke="white" strokeWidth="4" strokeLinecap="round" />
      <path d="M44 6v28" stroke="white" strokeWidth="4" strokeLinecap="round" />
      <rect x="12" y="8" width="11" height="10" rx="1.5" fill="white" opacity="0.55" />
      <rect x="26" y="8" width="11" height="10" rx="1.5" fill="white" opacity="0.55" />
      <rect x="12" y="20" width="11" height="10" rx="1.5" fill="white" opacity="0.55" />
      <rect x="26" y="20" width="11" height="10" rx="1.5" fill="white" opacity="0.55" />
      <path d="M4 32h22v9z" fill="white" />
    </svg>
  );
}
function IconFullscreen({ size = "w-[2.1vw]" }) {
  return (
    <svg viewBox="0 0 44 38" className={size} fill="none" aria-hidden="true">
      <path d="M2 12V2h10" stroke="white" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M32 2h10v10" stroke="white" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M42 26v10H32" stroke="white" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 36H2V26" stroke="white" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function PlayerPage() {
  const { titleId } = useParams();
  const [params] = useSearchParams();
  const nav = useNavigate();

  const [title, setTitle] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [season, setSeason] = useState(parseInt(params.get("season") || "1", 10));
  const [epNo, setEpNo] = useState(parseInt(params.get("ep") || "1", 10));
  const [playing, setPlaying] = useState(true);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [volume, setVolume] = useState(0.8);
  const [muted, setMuted] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [menu, setMenu] = useState(null); // null | "subs" | "audio" | "episodes"
  const [ended, setEnded] = useState(false);

  const videoRef = useRef(null);
  const hideTimer = useRef(null);
  const savedTimer = useRef(null);
  const wrapRef = useRef(null);

  const isSeries = title ? title.kind === "series" : false;
  const eps = useMemo(
    () => episodes.filter((e) => e.season === season).sort((a, b) => a.number - b.number),
    [episodes, season]
  );
  const idx = Math.max(0, eps.findIndex((e) => e.number >= epNo));
  const ep = eps.length ? eps[idx] : null;
  const seasons = useMemo(
    () => [...new Set(episodes.map((e) => e.season))].sort((a, b) => a - b),
    [episodes]
  );
  const nextEp = (() => {
    if (!isSeries) return null;
    const later = eps.slice(idx + 1)[0];
    if (later) return later;
    const ns = seasons.find((s) => s > season);
    if (ns) {
      const first = episodes.filter((e) => e.season === ns).sort((a, b) => a.number - b.number)[0];
      return first || null;
    }
    return null;
  })();

  // load title + episodes
  useEffect(() => {
    let live = true;
    api(`/api/titles/${titleId}`).then((r) => {
      if (live && r.ok) setTitle(r.data.item);
    });
    api(`/api/titles/${titleId}/episodes`).then((r) => {
      if (live && r.ok) {
        const items = r.data.items || [];
        setEpisodes(items);
        const s = new Set(items.map((e) => e.season));
        if (s.size && !s.has(parseInt(params.get("season") || "1", 10))) {
          setSeason([...s].sort((a, b) => a - b)[0]);
        }
      }
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [titleId]);

  // autoplay reliability: if the browser blocked unmuted autoplay, retry muted
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const t = setTimeout(() => {
      v.play().catch(() => {
        v.muted = true;
        setMuted(true);
        v.play().catch(() => {});
      });
    }, 250);
    return () => clearTimeout(t);
  }, [titleId, ep && ep.id]);

  // resume progress from continue-watching
  useEffect(() => {
    api("/api/continue-watching").then((r) => {
      if (!r.ok) return;
      const row = (r.data.items || []).find((m) => m.title_id === parseInt(titleId, 10));
      const v = videoRef.current;
      if (v && row && row.progress_seconds > 10 && row.progress_seconds < (v.duration || Infinity) - 15) {
        v.currentTime = row.progress_seconds;
      }
    });
  }, [titleId, episodes.length]);

  // save progress while playing (throttled)
  const saveProgress = useCallback(() => {
    const v = videoRef.current;
    if (!v || !title) return;
    if (savedTimer.current) return;
    savedTimer.current = setTimeout(() => {
      savedTimer.current = null;
      const body = { title_id: title.id, progress_seconds: Math.floor(v.currentTime) };
      if (ep && title.kind === "series") body.episode_id = ep.id;
      api("/api/continue-watching", { method: "POST", body });
    }, 1500);
  }, [title, ep]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => {
      setCurrent(v.currentTime);
      setDuration(v.duration || 0);
      try {
        const b = v.buffered;
        if (b.length) setBuffered(b.end(b.length - 1));
      } catch { /* ignore */ }
      saveProgress();
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
    };
  }, [saveProgress, titleId]);

  // auto-hide controls
  const poke = useCallback(() => {
    setShowControls(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setShowControls(false), 3200);
  }, []);
  useEffect(() => {
    poke();
    return () => hideTimer.current && clearTimeout(hideTimer.current);
  }, [poke]);

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play();
    else v.pause();
  };
  const seekBy = (d) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.min(Math.max(0, v.currentTime + d), v.duration || Infinity);
  };
  const toggleMute = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
  };
  const goFullscreen = () => {
    const el = wrapRef.current || document.documentElement;
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen && el.requestFullscreen();
  };
  const back = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    if (window.history.length > 2) nav(-1);
    else nav("/browse");
  };
  const pickEpisode = (e) => {
    setSeason(e.season);
    setEpNo(e.number);
    setEnded(false);
  };
  const onEnded = () => {
    setEnded(true);
    if (nextEp) {
      setTimeout(() => {
        setSeason(nextEp.season);
        setEpNo(nextEp.number);
        setEnded(false);
      }, 1500);
    }
  };

  if (!title) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center text-[#777]">
        Loading player…
      </div>
    );
  }

  const playedPct = duration ? (current / duration) * 100 : 0;
  const bufferedPct = duration ? Math.min(100, (buffered / duration) * 100) : 0;

  return (
    <div
      ref={wrapRef}
      className="fixed inset-0 bg-black"
      onMouseMove={poke}
      onClick={poke}
    >
      <video
        key={`${titleId}-${isSeries ? `${season}-${epNo}` : "movie"}`}
        ref={videoRef}
        src={title.video_url}
        autoPlay
        className="absolute inset-0 w-full h-full object-contain"
        onEnded={onEnded}
        onClick={togglePlay}
      />

      {/* top overlay: back arrow only */}
      <div
        className={`absolute top-0 inset-x-0 flex items-center transition-opacity duration-500 ${
          showControls ? "opacity-100" : "opacity-0"
        }`}
        style={{ paddingLeft: "2.0vw", paddingTop: "3.6vh" }}
      >
        <button onClick={back} aria-label="Back" className="p-0">
          <IconBack />
        </button>
      </div>

      {/* seek bar: red played / white buffered / gray track */}
      <div
        className={`absolute transition-opacity duration-500 ${showControls ? "opacity-100" : "opacity-0"}`}
        style={{ left: "1.15vw", right: "1.7vw", bottom: "12.3vh", height: "4px" }}
      >
        <div className="w-full h-full bg-[#6e6e6e]">
          <div className="absolute inset-y-0 left-0 bg-[#e8e8e8]" style={{ width: `${bufferedPct}%` }} />
          <div className="absolute inset-y-0 left-0 bg-[#e50914]" style={{ width: `${Math.min(playedPct, bufferedPct)}%` }} />
        </div>
        <input
          type="range"
          min={0}
          max={duration || 100}
          step={0.1}
          value={current}
          onChange={(e) => {
            const v = videoRef.current;
            if (v) v.currentTime = parseFloat(e.target.value);
          }}
          aria-label="Seek"
          className="absolute left-0 top-1/2 -translate-y-1/2 w-full cursor-pointer appearance-none bg-transparent"
          style={{ height: "2.4vh", WebkitAppearance: "none" }}
        />
      </div>

      {/* bottom gradient for control legibility */}
      <div
        className="absolute inset-x-0 bottom-0 pointer-events-none bg-gradient-to-t from-black/80 to-transparent"
        style={{ height: "15vh" }}
      />

      {/* control row */}
      <div
        className={`absolute inset-x-0 transition-opacity duration-500 ${showControls ? "opacity-100" : "opacity-0"}`}
        style={{ bottom: "3.2vh", height: "5vh", paddingLeft: "1.5vw", paddingRight: "1.5vw" }}
      >
        <div className="w-full h-full flex items-center relative">
          {/* left group */}
          <div className="flex items-center" style={{ gap: "2.6vw" }}>
            <button onClick={togglePlay} aria-label={playing ? "Pause" : "Play"} className="flex items-center h-full">
              {playing ? <IconPause /> : <IconPlay />}
            </button>
            <button onClick={() => seekBy(-10)} aria-label="Rewind 10 seconds" className="flex items-center h-full">
              <IconRewind />
            </button>
            <button onClick={() => seekBy(10)} aria-label="Forward 10 seconds" className="flex items-center h-full">
              <IconRewind flip />
            </button>
            <button onClick={toggleMute} aria-label={muted ? "Unmute" : "Mute"} className="flex items-center h-full">
              <IconVolume muted={muted} />
            </button>
          </div>

          {/* center: title + time */}
          <div className="absolute left-1/2 -translate-x-1/2 flex items-center text-white" style={{ gap: "1.5vw" }}>
            <span className="font-medium" style={{ fontSize: "1.8vh" }}>{title.name}</span>
            <span style={{ fontSize: "1.8vh" }}>
              {fmt(current)} / {fmt(duration)}
            </span>
          </div>

          {/* right group */}
          <div className="ml-auto flex items-center" style={{ gap: "2.9vw" }}>
            <div className="relative">
              <button
                onClick={() => setMenu(menu === "subs" ? null : "subs")}
                aria-label="Subtitles"
                className="flex items-center h-full"
              >
                <IconCC />
              </button>
              {menu === "subs" && (
                <div className="absolute bottom-[6vh] right-0 w-56 bg-black/95 border border-[#333] shadow-xl text-sm">
                  <div className="px-3 py-2 border-b border-[#333]">Subtitles</div>
                  {["Off", "English", "한국어"].map((s) => (
                    <button
                      key={s}
                      onClick={() => setMenu(null)}
                      className="w-full text-left px-3 py-2 hover:bg-[#232323]"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="relative">
              <button
                onClick={() => setMenu(menu === "audio" ? null : "audio")}
                aria-label="Audio"
                className="flex items-center h-full"
              >
                <IconAudio />
              </button>
              {menu === "audio" && (
                <div className="absolute bottom-[6vh] right-0 w-56 bg-black/95 border border-[#333] shadow-xl text-sm">
                  <div className="px-3 py-2 border-b border-[#333]">Audio</div>
                  {["English (Original)", "Description (English)"].map((s) => (
                    <button
                      key={s}
                      onClick={() => setMenu(null)}
                      className="w-full text-left px-3 py-2 hover:bg-[#232323]"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {isSeries && (
              <div className="relative">
                <button
                  onClick={() => setMenu(menu === "episodes" ? null : "episodes")}
                  aria-label="Episodes"
                  className="flex items-center h-full"
                >
                  <IconEpisodes />
                </button>
                {menu === "episodes" && (
                  <div className="absolute bottom-[6vh] right-0 w-80 max-h-80 overflow-y-auto bg-black/95 border border-[#333] shadow-xl">
                    <div className="px-3 py-2 border-b border-[#333] flex items-center justify-between">
                      <span className="font-semibold text-sm">All episodes</span>
                      <select
                        value={season}
                        onChange={(e) => setSeason(parseInt(e.target.value, 10))}
                        className="bg-[#2f2f2f] border border-[#4d4d4d] rounded text-xs p-0.5"
                      >
                        {seasons.map((s) => (
                          <option key={s} value={s}>Season {s}</option>
                        ))}
                      </select>
                    </div>
                    {eps.map((e) => (
                      <button
                        key={e.id}
                        onClick={() => { pickEpisode(e); setMenu(null); }}
                        className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-[#232323] ${
                          ep && e.id === ep.id ? "bg-[#2a2a2a]" : ""
                        }`}
                      >
                        <span className="text-[#777] w-5 text-center">{e.number}</span>
                        <div className="w-20 aspect-video rounded overflow-hidden bg-[#222] shrink-0">
                          <img src={e.thumbnail || title.backdrop} alt="" className="w-full h-full object-cover" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-xs truncate">{e.name}</div>
                          <div className="text-[10px] text-[#777]">{fmt(e.duration)}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {nextEp && (
              <button
                onClick={() => { setSeason(nextEp.season); setEpNo(nextEp.number); setEnded(false); }}
                className="flex items-center text-white font-medium"
                style={{ fontSize: "1.8vh" }}
              >
                Next
              </button>
            )}
            <button onClick={goFullscreen} aria-label="Fullscreen" className="flex items-center h-full">
              <IconFullscreen />
            </button>
          </div>
        </div>
      </div>

      {/* ended / next */}
      {ended && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/70">
          {nextEp ? (
            <>
              <div className="text-2xl font-semibold">Up next: S{nextEp.season}E{nextEp.number} {nextEp.name}</div>
              <div className="flex gap-4">
                <button
                  onClick={() => { setSeason(nextEp.season); setEpNo(nextEp.number); setEnded(false); }}
                  className="bg-white text-black font-semibold rounded px-8 py-3 hover:bg-white/80"
                >
                  Play next
                </button>
                <button
                  onClick={() => {
                    const v = videoRef.current;
                    if (v) { v.currentTime = 0; v.play(); }
                    setEnded(false);
                  }}
                  className="border border-[#6d6d6e] font-semibold rounded px-8 py-3 hover:border-white"
                >
                  Replay
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="text-2xl font-semibold">{title.name}</div>
              <button
                onClick={() => {
                  const v = videoRef.current;
                  if (v) { v.currentTime = 0; v.play(); }
                  setEnded(false);
                }}
                className="bg-white text-black font-semibold rounded px-8 py-3 hover:bg-white/80"
              >
                Replay
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
