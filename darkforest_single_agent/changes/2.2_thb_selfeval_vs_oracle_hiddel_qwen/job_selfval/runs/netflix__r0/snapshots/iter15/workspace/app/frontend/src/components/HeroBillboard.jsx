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
      <div className="absolute left-[5.8vw] w-[48vw]" style={{ top: "43vh" }}>
        {/* white NETFLIX wordmark above the title, like the reference billboard */}
        <img
          src="/assets/brand/netflix_wordmark.svg"
          alt="NETFLIX"
          className="w-[4.9vw] min-w-[80px]"
          style={{ filter: "invert(1)", marginBottom: "2.2vh" }}
        />
        <h1
          onClick={() => nav(`/title/${title.id}`)}
          className="font-display text-white leading-[0.98] uppercase drop-shadow-lg cursor-pointer select-none"
          style={{ fontSize: "7.6vw" }}
        >
          {title.name}
        </h1>
        <div className="mt-[3.6vh] flex items-center gap-[0.9vw] text-[15px] text-[#e5e5e5]">
          <span>{title.genre}</span>
          <span className="text-[#8c8c8c]">·</span>
          <span>{title.year}</span>
          <span className="text-[#8c8c8c]">·</span>
          <span>
            {title.kind === "series"
              ? seasons
                ? `${seasons} Season${seasons > 1 ? "s" : ""}`
                : "Series"
              : fmtDuration(title.duration) || "HD"}
          </span>
          {title.maturity_rating && (
            <>
              <span className="text-[#8c8c8c]">·</span>
              <span>{title.maturity_rating}</span>
            </>
          )}
        </div>
        <div className="mt-[4.2vh] flex items-center" style={{ gap: "1vw" }}>
          <button
            onClick={() => nav(`/watch/${title.id}`)}
            className="bg-white text-[#141414] font-semibold text-[15px] rounded px-[2.2vw] py-[1.2vh] hover:bg-white/85 transition-colors"
          >
            Play
          </button>
          <button
            onClick={() => nav(`/title/${title.id}`)}
            className="bg-[#636367]/60 text-white font-medium text-[15px] rounded px-[2.2vw] py-[1.2vh] hover:bg-[#636367]/80 transition-colors"
          >
            More Info
          </button>
        </div>
      </div>    </div>
  );
}
