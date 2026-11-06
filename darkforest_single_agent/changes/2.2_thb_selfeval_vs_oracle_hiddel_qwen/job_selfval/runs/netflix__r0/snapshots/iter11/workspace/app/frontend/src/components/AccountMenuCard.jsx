import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";

function fmtRemaining(sec) {
  if (!sec || sec <= 0) return "45 min left";
  const m = Math.max(1, Math.round(sec / 60));
  return `${m} min left`;
}

export default function AccountMenuCard({ onPlay }) {
  const [entry, setEntry] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    api("/api/continue-watching")
      .then((r) => {
        const items = unwrapItems(r);
        if (live && items.length) {
          setEntry({ title: items[0], progress: items[0].progress_seconds || 0, isCw: true });
        } else {
          return api("/api/titles/trending").then((t) => {
            const items = unwrapItems(t);
            if (live && items.length) setEntry({ title: items[0], progress: 0, isCw: false });
          });
        }
      })
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, []);

  const t = entry ? entry.title : null;
  const pct = entry && t && entry.isCw && t.duration
    ? Math.min(100, Math.max(8, Math.round((entry.progress / t.duration) * 100)))
    : 100;
  const R = 11;
  const CIRC = 2 * Math.PI * R;

  return (
    <div className="px-4 pb-4">
      <div className="relative h-[168px] bg-[#1d1d1d] rounded-sm overflow-hidden flex">
        <div className="w-[45px] shrink-0 bg-gradient-to-b from-[#b7cfdd] to-[#93a9b7]" />
        <div className="flex-1 flex flex-col pl-3 pr-3 pt-4 min-w-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="relative inline-flex w-[26px] h-[26px] shrink-0">
              <svg viewBox="0 0 26 26" className="w-[26px] h-[26px] -rotate-90">
                <circle cx="13" cy="13" r={R} fill="none" stroke="#3f4a52" strokeWidth="3" />
                <circle
                  cx="13" cy="13" r={R} fill="none" stroke="#e5e5e5" strokeWidth="3"
                  strokeDasharray={`${(pct / 100) * CIRC} ${CIRC}`} strokeLinecap="round"
                />
              </svg>
            </span>
            <span className="text-[18px] leading-6 text-white truncate font-light">
              {t ? t.name : "—"}
            </span>
          </div>
          <div className="mt-3.5 flex items-center gap-1.5 text-[13px] text-[#c9c9c9]">
            <svg viewBox="0 0 24 24" className="w-3 h-3 shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            <span className="truncate">
              {t
                ? (entry.isCw
                    ? `S1:E1 • ${fmtRemaining(t.duration - (entry.progress || 0))}`
                    : `${t.kind === "series" ? "Series" : "Movie"} • Watch now`)
                : ""}
            </span>
          </div>
          <div className="mt-auto h-[30px] bg-gradient-to-b from-[#a5bcc9] to-[#8fa7b6] flex items-center justify-center">
            <button
              onClick={() => t && onPlay && onPlay(t.title_id || t.id)}
              className="w-[128px] h-[22px] bg-[#e50914] hover:bg-[#c11119] text-white text-[12px] font-semibold rounded-[2px] transition-colors"
            >
              {entry && entry.isCw ? "Resume" : "Play"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
