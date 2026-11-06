import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, unwrapItems } from "../api";
import Rail from "../components/Rail";

export default function Games() {
  const [all, setAll] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const nav = useNavigate();

  useEffect(() => {
    api("/api/titles").then((r) => {
      if (!r.ok) return;
      const items = unwrapItems(r);
      setAll(items);
      setLoaded(true);
    });
  }, []);

  const feat = all[0] || null;
  const party = all.filter((t) => t.kind === "movie").slice(0, 10);

  return (
    <div className="pb-10">
      <div className="relative w-full overflow-hidden" style={{ height: "68vh", minHeight: 560 }}>
        <div className="absolute inset-0 bg-[#141414]" />
        {feat && (
          <img
            src={feat.backdrop || feat.poster}
            alt={feat.name}
            className="absolute inset-0 w-full h-full object-cover"
          />
        )}
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(90deg, rgba(10,8,10,0.96) 0%, rgba(10,8,10,0.82) 18%, rgba(10,8,10,0.25) 40%, rgba(10,8,10,0) 62%)"
          }}
        />
        <div className="absolute inset-x-0 bottom-0 h-[14vh] bg-gradient-to-t from-[#141414] to-transparent" />

        {feat && (
          <div className="absolute left-[2.7vw] bottom-[2.5vh] w-[24vw] min-w-[300px]">
            <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-[14px] w-[58px]" />
            <h1 className="font-display text-white leading-[1.02] mt-4" style={{ fontSize: "4.2vh" }}>
              {feat.name}
            </h1>
            <p className="text-[18px] text-[#e5e5e5] mt-2">
              {feat.genre}
              {feat.year ? ` · ${feat.year}` : ""}
            </p>
            <p className="text-[13px] text-[#9a9a9a] mt-4">
              Game · {feat.genre} · 1-4 Players · 10+ Minutes
            </p>
            <div className="mt-5 flex items-center gap-3">
              <button
                onClick={() => nav(`/watch/${feat.id}`)}
                className="bg-white text-[#141414] font-semibold text-[15px] rounded px-6 py-2.5 hover:bg-white/85 transition-colors"
              >
                Play Game
              </button>
              <button
                onClick={() => nav(`/title/${feat.id}`)}
                className="bg-[#4d4d4d]/60 text-white font-medium text-[15px] rounded px-6 py-2.5 hover:bg-[#4d4d4d]/80 transition-colors"
              >
                More Info
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="relative z-10 pt-[5vh]">
        <Rail title="Party Games" items={party} />
        <Rail title="More Games" items={all.slice(0, 12)} />
      </div>
    </div>
  );
}
