import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";
import Rail from "../components/Rail";

export default function NewPopular() {
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
    <div className="pt-[156px] pb-10">
      <Rail title="Top 10 TV Shows in the U.S. Today" items={topTv} numbered variant="top16" />
      <Rail title="Top 10 Movies in the U.S. Today" items={topMovies} numbered variant="top23" />
      <Rail title="New on Netflix" items={fresh} />
      <Rail title="Coming This Week" items={coming} />
    </div>
  );
}
