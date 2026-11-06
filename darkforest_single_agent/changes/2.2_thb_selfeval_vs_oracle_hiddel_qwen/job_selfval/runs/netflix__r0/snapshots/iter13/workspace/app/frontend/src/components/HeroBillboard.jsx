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
      <div className="absolute left-[5.8vw] w-[48vw]" style={{ top: "44.6vh" }}>
        {/* red NETFLIX wordmark badge */}
        <div
          className="w-fit rounded-[0.28vw] bg-[#e50914] flex items-center"
          style={{ height: "2.6vh", padding: "0 0.95vw", marginBottom: "2.1vh" }}
        >
          <span className="font-display text-white" style={{ fontSize: "1.35vw", letterSpacing: "0.04em" }}>
            NETFLIX
          </span>
        </div>
        <h1
          onClick={() => openTitleModal(title.id)}
          className="font-display text-[7vw] leading-[0.98] uppercase drop-shadow-lg cursor-pointer select-none"
        >
          {title.name}
        </h1>
        <p className="mt-[2.6vh] max-w-[40vw] text-[15px] text-[#e5e5e5] line-clamp-2 drop-shadow leading-snug">
          {title.synopsis}
        </p>
        <div className="mt-[3.4vh] flex items-center" style={{ gap: "1.5vw" }}>
          <button
            onClick={() => nav(`/watch/${title.id}`)}
            aria-label="Play"
            className="bg-[#e50914] rounded-[0.35vw] flex items-center justify-center hover:bg-[#f6121d] transition-colors"
            style={{ width: "2.5vw", height: "2.5vw", minWidth: 48, minHeight: 48 }}
          >
            <svg viewBox="0 0 24 24" style={{ width: "54%" }} fill="white" aria-hidden="true">
              <path d="M5 2.8l16.2 9.2L5 21.2V2.8z" />
            </svg>
          </button>
          <div className="flex items-center" style={{ gap: "1.15vw" }}>
            {title.rating != null && (
              <span className="text-[#46d369] font-semibold text-[14px]">{Math.round(title.rating * 10)}%</span>
            )}
            {title.year && <span className="text-[#e5e5e5] text-[14px]">{title.year}</span>}
            {title.kind === "series" && (
              <span className="text-[#e5e5e5] text-[14px]">
                {seasons ? `${seasons} Season${seasons > 1 ? "s" : ""}` : "Series"}
              </span>
            )}
            {title.kind === "movie" && fmtDuration(title.duration) && (
              <span className="text-[#e5e5e5] text-[14px]">{fmtDuration(title.duration)}</span>
            )}
            {title.maturity_rating && (
              <span className="border border-[#6d6d6e] pl-1.5 pr-1 py-px text-[12px] text-[#e5e5e5]">
                {title.maturity_rating}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
