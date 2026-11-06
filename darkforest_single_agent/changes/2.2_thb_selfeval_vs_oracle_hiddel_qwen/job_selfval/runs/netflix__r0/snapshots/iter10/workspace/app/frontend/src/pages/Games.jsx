import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";
import { useHero } from "../hooks";
import HeroBillboard from "../components/HeroBillboard";
import Rail from "../components/Rail";

export default function Games() {
  const hero = useHero();
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
        {hero && <HeroBillboard title={hero} eyebrow="Party Games" />}
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
