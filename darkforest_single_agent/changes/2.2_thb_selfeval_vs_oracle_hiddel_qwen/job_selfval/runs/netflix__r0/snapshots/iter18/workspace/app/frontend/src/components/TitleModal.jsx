import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, unwrapItems } from "../api";

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function langName(code) {
  const map = { en: "English", es: "Spanish", fr: "French", de: "German", it: "Italian", pt: "Portuguese", ja: "Japanese", ko: "Korean", hi: "Hindi" };
  return code ? map[code] || code.toUpperCase() : null;
}

export default function TitleModal({ id, onClose }) {
  const nav = useNavigate();
  const [title, setTitle] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [season, setSeason] = useState(1);
  const [inList, setInList] = useState(null);

  useEffect(() => {
    let live = true;
    setEpisodes([]);
    setSeason(1);
    setTitle(null);
    setInList(null);
    api(`/api/titles/${id}`).then((r) => {
      if (live && r.ok) setTitle(r.data.item);
    });
    api("/api/my-list").then((r) => {
      if (live && r.ok) setInList(unwrapItems(r).some((m) => m.title_id === id));
    });
    return () => { live = false; };
  }, [id]);

  const toggleList = async () => {
    if (!title) return;
    const was = inList === null ? false : inList;
    if (was) {
      const r = await api("/api/my-list");
      if (r.ok) {
        const row = unwrapItems(r).find((m) => m.title_id === title.id);
        if (row) await api(`/api/my-list/${row.id}`, { method: "DELETE" });
      }
      setInList(false);
    } else {
      await api("/api/my-list", { method: "POST", body: { title_id: title.id } });
      setInList(true);
    }
  };

  useEffect(() => {
    if (!title || title.kind !== "series") return;
    api(`/api/titles/${id}/episodes`).then((r) => {
      if (r.ok) setEpisodes(r.data.items || []);
    });
  }, [id, title && title.kind]);

  const seasons = useMemo(
    () => [...new Set(episodes.map((e) => e.season))].sort((a, b) => a - b),
    [episodes]
  );
  const eps = episodes
    .filter((e) => e.season === (seasons.length ? season : 1))
    .sort((a, b) => a.number - b.number);

  if (!title) {
    return (
      <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center" onMouseDown={onClose}>
        <div className="text-[#999]">Loading…</div>
      </div>
    );
  }

  const img = title.backdrop || title.poster;
  const language = langName(title.language);

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-gradient-to-b from-[#1a1a1a] to-[#050505]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full pb-16">
        {/* backdrop hero */}
        <div className="relative h-[53.6vh] min-h-[420px]">
          <img src={img} alt={title.name} className="absolute inset-0 w-full h-full object-cover" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#0a0a0a] via-transparent to-black/25" />
          <button
            onClick={onClose}
            aria-label="Close"
            className="absolute top-5 right-5 w-10 h-10 rounded-full bg-black/50 border border-[#4d4d4d] flex items-center justify-center hover:bg-black/70"
          >
            <img src="/assets/icons/x.svg" alt="" className="w-5 h-5 invert" />
          </button>
          <div className="absolute left-[24.7vw] bottom-[1.5vh] flex items-end gap-[1.8vw]">
            <button
              onClick={() => nav(`/watch/${title.id}`)}
              aria-label={`Play ${title.name}`}
              className="text-left font-display text-[4.7vw] max-w-[52vw] leading-[1.05] uppercase text-white drop-shadow-lg hover:brightness-110"
            >
              {title.name}
            </button>
            <div className="flex items-center pb-[1vh]" style={{ gap: "1vw" }}>
              <button
                onClick={() => nav(`/watch/${title.id}`)}
                aria-label="Play"
                className="flex items-center gap-2 bg-white text-[#141414] font-semibold rounded px-[1.4vw] py-[0.7vh] hover:bg-white/85 transition-colors"
                style={{ fontSize: "15px" }}
              >
                <img src="/assets/icons/play.svg" alt="" className="w-[18px] h-[18px]" />
                Play
              </button>
              <button
                onClick={toggleList}
                aria-label={inList ? "Remove from My List" : "Add to My List"}
                className="w-[42px] h-[42px] rounded-full border-[3px] border-[#6d6d6e] bg-black/30 flex items-center justify-center hover:border-white transition-colors"
              >
                <img src={inList ? "/assets/icons/check.svg" : "/assets/icons/plus.svg"} alt="" className="w-[18px] h-[18px] invert" />
              </button>
              <button
                onClick={() => window.dispatchEvent(new CustomEvent("nf:rate", { detail: { id: title.id } }))}
                aria-label="Rate this title"
                className="w-[42px] h-[42px] rounded-full border-[3px] border-[#6d6d6e] bg-black/30 flex items-center justify-center hover:border-white transition-colors"
              >
                <img src="/assets/icons/thumbs-up.svg" alt="" className="w-[18px] h-[18px] invert" />
              </button>
            </div>
          </div>
        </div>

        {/* centered content */}
        <div className="mx-auto w-[49.8vw] min-w-[680px] max-w-full">
          <div className="mt-[6vh] flex gap-[3vw]">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-3 text-[13px]">
                {title.rating != null && (
                  <span className="text-[#46d369] font-semibold">{Math.round(title.rating * 10)}% Match</span>
                )}
                {title.year && <span className="text-[#e5e5e5]">{title.year}</span>}
                {title.kind === "series" && seasons.length > 0 && (
                  <span className="text-[#e5e5e5]">{seasons.length} Season{seasons.length > 1 ? "s" : ""}</span>
                )}
                {title.kind === "movie" && fmtDuration(title.duration) && (
                  <span className="text-[#e5e5e5]">{fmtDuration(title.duration)}</span>
                )}
                {title.maturity_rating && (
                  <span className="border border-[#6d6d6e] px-1.5 text-[11px]">{title.maturity_rating}</span>
                )}
              </div>
              {language && (
                <div className="mt-[1.5vh] text-[12px] text-[#999]">
                  Original Language: <span className="text-[#e5e5e5]">{language}</span>
                </div>
              )}
              <p className="mt-[4.2vh] text-[15px] leading-[1.9] text-[#e5e5e5] line-clamp-3">
                {title.synopsis}
              </p>
            </div>
            <div className="shrink-0 text-[13px] text-[#777]">
              <div>
                <span>Genres: </span>
                <span className="text-[#e5e5e5]">{(title.genres || [title.genre]).filter(Boolean).join(", ")}</span>
              </div>
              <div className="mt-[2.3vh]">
                <span>Maturity: </span>
                <span className="text-[#e5e5e5]">{title.maturity_rating || "—"}</span>
              </div>
              <div className="mt-[1.2vh] text-[11px]">
                Quality: <span className="text-[#e5e5e5]">HD</span>
              </div>
              {language && (
                <div className="mt-[2.8vh] text-[11px]">
                  Audio: <span className="text-[#e5e5e5]">{language}</span>
                </div>
              )}
              {language && (
                <div className="mt-[1.2vh] text-[11px]">
                  Subtitles: <span className="text-[#e5e5e5]">{language}</span>
                </div>
              )}
            </div>
          </div>

          {episodes.length > 0 && (
            <div className="mt-[6.7vh]">
              <div className="flex items-center gap-4">
                <h3 className="text-[22px] font-semibold text-white">Episodes</h3>
                {seasons.length > 1 && (
                  <select
                    value={season}
                    onChange={(e) => setSeason(parseInt(e.target.value, 10))}
                    aria-label="Season"
                    className="ml-auto bg-[#141414] border border-[#4d4d4d] rounded px-3 py-1.5 text-[14px] text-[#e5e5e5]"
                  >
                    {seasons.map((s) => (
                      <option key={s} value={s}>
                        Season {s}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="mt-[3vh] space-y-[4.5vh]">
                {eps.map((e) => (
                  <div key={e.id}>
                    <div className="flex items-center gap-4 text-[15px]">
                      <span className="text-[#777] w-5 text-center shrink-0">{e.number}</span>
                      <span className="font-semibold text-[#e5e5e5] truncate">{e.name}</span>
                      <span className="text-[#777] text-[13px] shrink-0">{fmtDuration(e.duration)}</span>
                    </div>
                    <button
                      onClick={() => nav(`/watch/${title.id}?season=${e.season}&ep=${e.number}`)}
                      aria-label={`Play episode ${e.number}`}
                      className="mt-[1.4vh] w-full h-[11.6vh] min-h-[96px] max-h-[150px] bg-[#212121] rounded flex items-center gap-6 p-5 hover:bg-[#2a2a2a] transition-colors text-left"
                    >
                      <img
                        src={e.thumbnail || title.backdrop || title.poster}
                        alt={e.name}
                        className="w-[156px] min-w-[140px] aspect-video object-cover rounded shrink-0"
                        loading="lazy"
                      />
                      <p className="min-w-0 flex-1 self-center text-[13px] leading-[1.7] text-[#999] line-clamp-3">
                        {e.synopsis}
                      </p>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
