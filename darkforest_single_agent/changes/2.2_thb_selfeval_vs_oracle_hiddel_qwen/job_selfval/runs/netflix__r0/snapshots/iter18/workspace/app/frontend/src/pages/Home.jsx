import { useEffect, useState, useMemo } from "react";
import { api, unwrapItems } from "../api";
import { useGenreId } from "../hooks";
import HeroBillboard from "../components/HeroBillboard";
import Rail from "../components/Rail";

export default function Home() {
  const [hero, setHero] = useState(null);
  const [trending, setTrending] = useState([]);
  const [cont, setCont] = useState([]);
  const [only, setOnly] = useState([]);
  const [fresh, setFresh] = useState([]);
  const actionId = useGenreId("Action & Adventure");
  const [action, setAction] = useState([]);

  useEffect(() => {
    Promise.all([
      api("/api/titles/top10?kind=series"),
      api("/api/titles/trending"),
      api("/api/continue-watching"),
      api("/api/titles?year=2026")
    ]).then(([top10, trend, cw, year]) => {
      if (top10.ok) setHero(top10.data.items?.[0] || null);
      setTrending(trend.ok ? unwrapItems(trend) : []);
      setCont(cw.ok ? unwrapItems(cw).map((t) => ({
        ...t, id: t.title_id,
        progress_pct: t.duration ? Math.min(98, Math.round((t.progress_seconds / t.duration) * 100)) : null
      })) : []);
      setFresh(year.ok ? unwrapItems(year) : []);
    });
  }, []);

  useEffect(() => {
    if (actionId == null) return;
    api(`/api/genres/${actionId}/titles?kind=series`).then((r) => {
      if (r.ok) setAction(unwrapItems(r));
    });
  }, [actionId]);

  // series-only list for "Only on Netflix" (top rated series)
  useEffect(() => {
    api("/api/titles?kind=series").then((r) => {
      if (!r.ok) return;
      const s = [...unwrapItems(r)].sort((a, b) => (b.rating || 0) - (a.rating || 0));
      setOnly(s.slice(0, 12));
    });
  }, []);

  const games = useMemo(
    () => trending.filter((t) => t.kind === "movie").slice(0, 10),
    [trending]
  );

  return (
    <div className="pt-0 pb-10">
      {hero && <HeroBillboard title={hero} />}
      <div className="relative z-10 pt-[5vh]">
        <Rail title="Trending Now" items={trending} />
        {cont.length > 0 && <Rail title={"Continue Watching for You"} items={cont} />}
        <Rail title="TV Action & Adventure" items={action} titleLink={actionId ? `/browse/genre/${actionId}` : null} />
        <Rail title="Games" items={games} titleLink="/games" />
        <Rail title="Only on Netflix" items={only} />
        <Rail title="Top Searches" items={trending.slice(2, 14)} />
        <Rail title="New on Netflix" items={fresh} titleLink="/new" />
      </div>
    </div>
  );
}
