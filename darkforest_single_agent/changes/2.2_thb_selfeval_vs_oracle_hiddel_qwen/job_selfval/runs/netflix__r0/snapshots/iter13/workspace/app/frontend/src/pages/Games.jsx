import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";
import Rail from "../components/Rail";

export default function Games() {
  const [party, setParty] = useState([]);
  const [all, setAll] = useState([]);

  useEffect(() => {
    api("/api/titles").then((r) => {
      if (!r.ok) return;
      const items = unwrapItems(r);
      setAll(items);
      setParty(items.filter((t) => t.kind === "movie").slice(0, 10));
    });
  }, []);

  return (
    <div className="pb-10">
      <div className="relative">
        <div
          className="relative w-full flex items-center justify-center overflow-hidden"
          style={{ height: "56vh", minHeight: 460 }}
        >
          <div className="absolute inset-0 bg-[#141414]" />
          <div
            className="absolute inset-0"
            style={{ background: "radial-gradient(ellipse 60% 55% at 50% 42%, rgba(229,9,20,0.22) 0%, rgba(20,20,20,0) 70%)" }}
          />
          <div className="absolute inset-x-0 bottom-0 h-[10vh] bg-gradient-to-t from-[#141414] to-transparent" />
          <div className="relative flex items-center" style={{ gap: "2.2vw" }}>
            <img src="/assets/brand/netflix_n_icon.svg" alt="" className="drop-shadow-2xl" style={{ width: "7.5vw", height: "7.5vw" }} />
            <h1 className="font-display text-white tracking-wide" style={{ fontSize: "6.5vw" }}>
              Games
            </h1>
          </div>
        </div>
        <div className="absolute top-[15vh] inset-x-0 z-10 px-[3.5vw]">
          <h2 className="text-[26px] font-semibold drop-shadow">Games</h2>
        </div>
      </div>
      <div className="relative z-10 pt-[5vh]">
        <Rail title="Party Games" items={party} />
        <Rail title="More Games" items={all.slice(0, 12)} />
      </div>
    </div>
  );
}
