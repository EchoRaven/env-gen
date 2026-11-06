import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { openTitleModal } from "../App";

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

export default function HeroBillboard({ title, tall = true }) {
  const nav = useNavigate();
  const [seasons, setSeasons] = useState(null);

  useEffect(() => {
    let live = true;
    setSeasons(null);
    if (title && title.kind === "series") {
      api(`/api/titles/${title.id}/episodes`).then((r) => {
        if (!live || !r.ok) return;
        const s = new Set((r.data.items || []).map((e) => e.season)).size;
        setSeasons(s || 1);
      });
    }
    return () => { live = false; };
  }, [title && title.id]);

  if (!title) return null;
  const img = title.backdrop || title.poster;

  return (
    <div className={`relative w-full ${tall ? "h-[56vh] min-h-[420px]" : "h-[42vh] min-h-[300px]"}`}>
      <img src={img} alt={title.name} className="absolute inset-0 w-full h-full object-cover" />
      <div className="absolute inset-0 bg-gradient-to-r from-black/80 via-black/30 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-[#141414] to-transparent" />
      <div className="absolute bottom-[12%] left-4 md:left-[4vw] max-w-xl">
        <h1 className="font-display text-4xl md:text-6xl leading-[0.95] drop-shadow-lg uppercase">
          {title.name}
        </h1>
        <div className="mt-3 flex items-center gap-3 text-sm">
          {title.rating != null && (
            <span className="text-[#46d369] font-semibold">{Math.round(title.rating * 10)}% Match</span>
          )}
          {title.maturity_rating && (
            <span className="border border-[#6d6d6e] pl-1.5 pr-1 py-px text-[11px]">{title.maturity_rating}</span>
          )}
          {title.year && <span className="text-[#e5e5e5]">{title.year}</span>}
          {title.kind === "series" && (
            <span className="text-[#e5e5e5]">
              {seasons ? `${seasons} Season${seasons > 1 ? "s" : ""}` : "Series"}
            </span>
          )}
          {title.kind === "movie" && fmtDuration(title.duration) && (
            <span className="text-[#e5e5e5]">{fmtDuration(title.duration)}</span>
          )}
        </div>
        <p className="mt-3 text-sm md:text-base text-[#e5e5e5] line-clamp-3 drop-shadow">
          {title.synopsis}
        </p>
        <div className="mt-5 flex items-center gap-3">
          <button
            onClick={() => nav(`/watch/${title.id}`)}
            className="flex items-center gap-2 bg-white text-black font-semibold rounded px-6 py-2.5 hover:bg-white/80 transition-colors"
          >
            <img src="/assets/icons/play.svg" alt="" className="w-5 h-5" style={{ filter: "invert(0)" }} />
            Play
          </button>
          <button
            onClick={() => openTitleModal(title.id)}
            className="flex items-center gap-2 bg-[#6d6d6e]/60 text-white font-semibold rounded px-5 py-2.5 hover:bg-[#6d6d6e]/40 transition-colors"
          >
            <img src="/assets/icons/info.svg" alt="" className="w-5 h-5 invert" />
            More Info
          </button>
        </div>
      </div>
    </div>
  );
}
