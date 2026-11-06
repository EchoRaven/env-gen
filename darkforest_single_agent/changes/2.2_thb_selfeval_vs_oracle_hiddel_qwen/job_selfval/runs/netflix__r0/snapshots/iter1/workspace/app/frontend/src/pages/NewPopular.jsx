import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";
import { useHero } from "../hooks";
import HeroBillboard from "../components/HeroBillboard";
import Rail from "../components/Rail";

export default function NewPopular() {
  const hero = useHero();
  const [topTv, setTopTv] = useState([]);
  const [topMovies, setTopMovies] = useState([]);
  const [fresh, setFresh] = useState([]);
  const [coming, setComing] = useState([]);

  useEffect(() => {
    api("/api/titles/top10?kind=series").then((r) => {
      if (r.ok) setTopTv(unwrapItems(r));
    });
    api("/api/titles/top10?kind=movie").then((r) => {
      if (r.ok) setTopMovies(unwrapItems(r));
    });
    api("/api/titles?year=2026").then((r) => {
      if (!r.ok) return;
      const items = unwrapItems(r);
      setFresh(items.slice(0, 12));
      setComing(items.slice(4, 16));
    });
  }, []);

  return (
    <div className="pt-0 pb-10">
      {hero && <HeroBillboard title={hero} tall={false} />}
      <div className="relative z-10 -mt-8 md:-mt-10">
        <div className="px-4 md:px-[4vw] mb-2">
          <h2 className="text-lg md:text-xl font-semibold">New & Popular</h2>
        </div>
        <Rail title="Top 10 TV Shows" items={topTv} numbered />
        <Rail title="Top 10 Movies" items={topMovies} numbered />
        <Rail title="New on Netflix" items={fresh} />
        <Rail title="Coming This Week" items={coming} />
      </div>
    </div>
  );
}
