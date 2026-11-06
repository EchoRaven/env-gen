import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, unwrapItems } from "../api";
import { openTitleModal } from "../App";

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

const SIZES = {
  rail: "w-[18.3vw] min-w-[150px] aspect-video",
  top16: "w-[15.15vw] min-w-[130px] aspect-video",
  top23: "w-[7.3vw] min-w-[100px] aspect-[2/3]",
  mylist: "w-full aspect-[9/8]",
  lang: "w-full aspect-video",
  grid: "w-full aspect-video"
};

export default function Card({ title, rank, variant = "rail", titleBelow = false }) {
  const nav = useNavigate();
  const [inList, setInList] = useState(null);
  const [seasons, setSeasons] = useState(null);

  const checkList = async () => {
    if (inList === null) {
      const r = await api("/api/my-list");
      if (r.ok) setInList(unwrapItems(r).some((m) => m.title_id === title.id));
    }
    if (title.kind === "series" && seasons === null) {
      api(`/api/titles/${title.id}/episodes`).then((r) => {
        if (r.ok) {
          const s = new Set((r.data.items || []).map((e) => e.season));
          setSeasons(s.size || 1);
        }
      });
    }
  };

  const toggleList = async (e) => {
    e.stopPropagation();
    if (inList === null) await checkList();
    if (inList) {
      const r = await api("/api/my-list");
      const row = unwrapItems(r).find((m) => m.title_id === title.id);
      if (row) await api(`/api/my-list/${row.id}`, { method: "DELETE" });
      setInList(false);
    } else {
      await api("/api/my-list", { method: "POST", body: { title_id: title.id } });
      setInList(true);
    }
  };

  const rate = () => {
    window.dispatchEvent(new CustomEvent("nf:rate", { detail: { id: title.id } }));
  };

  const img = variant === "mylist" ? (title.poster || title.backdrop) : (title.backdrop || title.poster);

  const hoverPanel = (
    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/95 via-black/70 to-transparent pt-8 pb-2.5 px-2.5 opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-20">
      <div className="flex items-center gap-1.5">
        <button
          onClick={(e) => { e.stopPropagation(); nav(`/watch/${title.id}`); }}
          aria-label="Play"
          className="w-8 h-8 rounded-full bg-white flex items-center justify-center hover:bg-white/80"
        >
          <img src="/assets/icons/play.svg" alt="" className="w-4 h-4" />
        </button>
        <button
          onClick={toggleList}
          aria-label={inList ? "Remove from My List" : "Add to My List"}
          className="w-8 h-8 rounded-full border border-[#6d6d6e] flex items-center justify-center hover:border-white bg-black/40"
        >
          {inList === true ? (
            <img src="/assets/icons/check.svg" alt="" className="w-4 h-4 invert" />
          ) : (
            <img src="/assets/icons/plus.svg" alt="" className="w-4 h-4 invert" />
          )}
        </button>
        <button
          onClick={rate}
          aria-label="Rate this title"
          className="w-8 h-8 rounded-full border border-[#6d6d6e] flex items-center justify-center hover:border-white bg-black/40"
        >
          <img src="/assets/icons/thumbs-up.svg" alt="" className="w-4 h-4 invert" />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); openTitleModal(title.id); }}
          aria-label="More info"
          className="ml-auto w-8 h-8 rounded-full border border-[#6d6d6e] flex items-center justify-center hover:border-white bg-black/40"
        >
          <img src="/assets/icons/chevron-down.svg" alt="" className="w-4 h-4 invert rotate-180" />
        </button>
      </div>
      <div className="mt-2 flex items-center gap-2 text-[11px]">
        {title.rating != null && (
          <span className="text-[#46d369] font-semibold">{Math.round(title.rating * 10)}%</span>
        )}
        {title.maturity_rating && (
          <span className="border border-[#6d6d6e] px-1 text-[10px]">{title.maturity_rating}</span>
        )}
        <span className="text-[#e5e5e5]">
          {title.kind === "movie"
            ? fmtDuration(title.duration)
            : seasons
            ? `${seasons} Season${seasons > 1 ? "s" : ""}`
            : "Series"}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-[#999]">
        {(title.genres || []).slice(0, 3).map((g) => (
          <span key={g}>{g}</span>
        ))}
      </div>
      <div className="mt-1 text-[13px] text-white truncate">{title.name}</div>
    </div>
  );

  const media = (
    <div
      className={`relative rounded overflow-hidden bg-[#1f1f1f] ring-white transition duration-200 group-hover:scale-[1.25] group-hover:z-10 group-hover:shadow-2xl ${SIZES[variant] || SIZES.rail}`}
    >
      <img src={img} alt={title.name} className="w-full h-full object-cover" loading="lazy" />
      {title.progress_pct != null && (
        <div className="absolute bottom-0 left-0 right-0 h-[3px] bg-[#555]/70 z-10">
          <div className="h-full bg-[#e50914]" style={{ width: `${title.progress_pct}%` }} />
        </div>
      )}
      {hoverPanel}
    </div>
  );

  if (variant === "top23" && rank) {
    return (
      <div
        className="group relative shrink-0 w-[15.45vw] min-w-[140px] flex items-end justify-end cursor-pointer"
        onClick={() => nav(`/title/${title.id}`)}
        onMouseEnter={checkList}
      >
        <div className="pointer-events-none select-none leading-none w-[7.8vw] min-w-[72px] text-right overflow-visible flex justify-end">
          <span className="top10-numeral text-[14.5vw] block whitespace-nowrap">{rank}</span>
        </div>
        <div className="w-[7.3vw] min-w-[64px]">{media}</div>
      </div>
    );
  }

  if (variant === "top16" && rank) {
    return (
      <div
        className="group relative shrink-0 cursor-pointer w-[15.15vw] min-w-[130px]"
        onClick={() => nav(`/title/${title.id}`)}
        onMouseEnter={checkList}
      >
        {media}
        <div className="pointer-events-none select-none absolute -bottom-[1px] -left-[0.2vw] z-20 leading-none">
          <span className="top10-numeral text-[11.8vw] block whitespace-nowrap">{rank}</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`group relative shrink-0 cursor-pointer ${variant === "rail" ? "w-[18.3vw] min-w-[150px]" : ""}`}
      onClick={() => nav(`/title/${title.id}`)}
      onMouseEnter={checkList}
    >
      {media}
      {titleBelow && (
        <div className="mt-1.5 text-[13px] text-[#e5e5e5] truncate group-hover:opacity-0 transition-opacity">
          {title.name}
        </div>
      )}
    </div>
  );
}
