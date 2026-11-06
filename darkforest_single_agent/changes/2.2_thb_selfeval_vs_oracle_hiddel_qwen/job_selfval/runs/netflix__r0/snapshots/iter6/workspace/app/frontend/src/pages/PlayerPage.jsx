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
  const changeVolume = (val) => {
    const v = videoRef.current;
    if (!v) return;
    v.volume = val;
    setVolume(val);
    v.muted = val === 0;
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

  const videoSrc = isSeries && ep ? title.video_url : title.video_url;
  const episodeLabel = isSeries && ep ? `S${ep.season}E${ep.number} · ${ep.name}` : title.name;

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
        src={videoSrc}
        autoPlay
        className="absolute inset-0 w-full h-full object-contain"
        onEnded={onEnded}
        onClick={togglePlay}
      />
      {/* title overlay */}
      <div
        className={`absolute top-0 inset-x-0 flex items-center justify-between px-6 pt-5 transition-opacity duration-500 ${
          showControls ? "opacity-100" : "opacity-0"
        }`}
      >
        <button onClick={back} aria-label="Back" className="p-2">
          <img src="/assets/icons/netflix/arrow_left.svg" alt="" className="w-8 h-8 invert" />
        </button>
        <div className="text-center">
          <div className="text-lg font-semibold drop-shadow">{title.name}</div>
          {isSeries && ep && (
            <div className="text-sm text-[#b3b3b3]">{episodeLabel}</div>
          )}
        </div>
        <div className="w-10" />
      </div>

      {/* ended / next */}
      {ended && nextEp && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/70">
          <div className="text-2xl font-semibold">Up next: S{nextEp.season}E{nextEp.number} {nextEp.name}</div>
          <div className="flex gap-4">
            <button
              onClick={() => { setSeason(nextEp.season); setEpNo(nextEp.number); setEnded(false); }}
              className="bg-white text-black font-semibold rounded px-8 py-3 hover:bg-white/80"
            >
              Play next
            </button>
            <button
              onClick={() => setEnded(false)}
              className="border border-[#6d6d6e] font-semibold rounded px-8 py-3 hover:border-white"
            >
              Replay
            </button>
          </div>
        </div>
      )}

      {/* control bar */}
      <div
        className={`absolute bottom-0 inset-x-0 px-4 md:px-8 pb-[44px] pt-10 transition-opacity duration-500 bg-gradient-to-t from-black/90 to-transparent ${
          showControls ? "opacity-100" : "opacity-0"
        }`}
      >
        {/* seek */}
        <input
          type="range"
          className="seek w-full cursor-pointer"
          min={0}
          max={duration || 100}
          step={0.1}
          value={current}
          onChange={(e) => {
            const v = videoRef.current;
            if (v) v.currentTime = parseFloat(e.target.value);
          }}
          style={{
            background: `linear-gradient(to right, #e50914 ${(duration ? (current / duration) * 100 : 0)}%, #555 ${(duration ? (current / duration) * 100 : 0)}%)`
          }}
        />
        <div className="flex items-center gap-3 md:gap-5 mt-6">
          <button onClick={togglePlay} aria-label={playing ? "Pause" : "Play"} className="p-1">
            <img src={playing ? "/assets/icons/pause.svg" : "/assets/icons/play.svg"} alt="" className="w-7 h-7 invert" />
          </button>
          <button onClick={() => seekBy(-10)} aria-label="Rewind 10 seconds" className="p-1">
            <span className="text-lg leading-none font-semibold">−10s</span>
          </button>
          <button onClick={() => seekBy(10)} aria-label="Forward 10 seconds" className="p-1">
            <span className="text-lg leading-none font-semibold">+10s</span>
          </button>
          <div className="flex items-center gap-2">
            <button onClick={toggleMute} aria-label="Mute">
              <img src={muted ? "/assets/icons/volume-x.svg" : "/assets/icons/volume-2.svg"} alt="" className="w-6 h-6 invert" />
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              onChange={(e) => changeVolume(parseFloat(e.target.value))}
              className="seek w-16 md:w-24"
              style={{
                background: `linear-gradient(to right, #fff ${(muted ? 0 : volume) * 100}%, #555 ${(muted ? 0 : volume) * 100}%)`
              }}
            />
          </div>
          <div className="ml-auto flex items-center gap-3 md:gap-5 text-sm">
            <span className="text-[#e5e5e5]">
              {fmt(current)} / {fmt(duration)}
            </span>
            {isSeries && (
              <div className="relative">
                <button
                  onClick={() => setMenu(menu === "episodes" ? null : "episodes")}
                  className="flex items-center gap-1.5"
                >
                  <span>Episodes</span>
                  <img src="/assets/icons/chevron-down.svg" alt="" className="w-3 h-3 invert" />
                </button>
                {menu === "episodes" && (
                  <div className="absolute bottom-10 right-0 w-80 max-h-80 overflow-y-auto bg-black/95 border border-[#333] shadow-xl">
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
            <div className="relative">
              <button
                onClick={() => setMenu(menu === "subs" ? null : "subs")}
                className="flex items-center gap-1"
              >
                <img src="/assets/icons/netflix/subtitles.svg" alt="" className="w-6 h-6 invert" />
              </button>
              {menu === "subs" && (
                <div className="absolute bottom-10 right-0 w-56 bg-black/95 border border-[#333] shadow-xl text-sm">
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
                className="flex items-center gap-1"
              >
                <img src="/assets/icons/netflix/audio_description.svg" alt="" className="w-6 h-6 invert" />
              </button>
              {menu === "audio" && (
                <div className="absolute bottom-10 right-0 w-56 bg-black/95 border border-[#333] shadow-xl text-sm">
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
            {nextEp && (
              <button
                onClick={() => { setSeason(nextEp.season); setEpNo(nextEp.number); setEnded(false); }}
                className="flex items-center gap-1.5 font-semibold"
              >
                Next
                <img src="/assets/icons/netflix/new_episode.svg" alt="" className="w-5 h-5 invert" />
              </button>
            )}
            <button onClick={goFullscreen} aria-label="Fullscreen">
              <img src="/assets/icons/maximize.svg" alt="" className="w-6 h-6 invert" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
