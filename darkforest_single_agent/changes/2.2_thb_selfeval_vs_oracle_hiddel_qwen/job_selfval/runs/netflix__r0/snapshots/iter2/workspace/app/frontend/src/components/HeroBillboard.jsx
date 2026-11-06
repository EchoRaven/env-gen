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
    <div className={`relative w-full ${tall ? "h-[82vh] min-h-[620px]" : "h-[62vh] min-h-[480px]"}`}>
      <img src={img} alt={title.name} className="absolute inset-0 w-full h-full object-cover" />
      <div className="absolute inset-0 bg-gradient-to-r from-black/85 via-black/35 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 h-[12vh] bg-gradient-to-t from-[#141414] via-[#141414]/60 to-transparent" />
      <div className="absolute left-[6.25vw] max-w-[46vw] top-[39vh] bottom-[2.5vh] flex flex-col">
        <h1 className="font-display text-[3.4vw] leading-[1.02] uppercase drop-shadow-lg">{title.name}</h1>
        <p className="mt-[1.1vw] text-[18px] leading-[1.55] text-[#e5e5e5] line-clamp-5 drop-shadow">
          {title.synopsis}
        </p>
        <div className="mt-[1.1vw] flex items-center gap-3 text-[13px]">
          {title.rating != null && (
            <span className="text-[#46d369] font-semibold">{Math.round(title.rating * 10)}% Match</span>
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
          {title.maturity_rating && (
            <span className="border border-[#6d6d6e] pl-1.5 pr-1 py-px text-[11px]">{title.maturity_rating}</span>
          )}
        </div>
        <div className="mt-auto flex items-center gap-3">
          <button
            onClick={() => nav(`/watch/${title.id}`)}
            className="flex items-center gap-2.5 bg-white text-black font-semibold rounded px-[2.2vw] py-[0.6vw] hover:bg-white/80 transition-colors"
          >
            <img src="/assets/icons/play.svg" alt="" className="w-6 h-6" style={{ filter: "invert(0)" }} />
            Play
          </button>
          <button
            onClick={() => openTitleModal(title.id)}
            className="flex items-center gap-2.5 bg-[#6d6d6e]/50 text-white font-semibold rounded px-[1.9vw] py-[0.6vw] hover:bg-[#6d6d6e]/35 transition-colors backdrop-blur-sm"
          >
            <img src="/assets/icons/info.svg" alt="" className="w-6 h-6 invert" />
            More Info
          </button>
        </div>
      </div>
    </div>
  );
}
