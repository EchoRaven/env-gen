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
    <div className="pt-0 pb-10">
      {hero && <HeroBillboard title={hero} />}
      <div className="relative z-10 -mt-10 md:-mt-16">
        <div className="px-4 md:px-[4vw] mb-2">
          <h2 className="text-lg md:text-xl font-semibold">Games</h2>
        </div>
        <Rail title="Party Games" items={party} />
        <Rail title="More Games" items={all.slice(0, 12)} />
      </div>
    </div>
  );
}
