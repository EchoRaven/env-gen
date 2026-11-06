import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";
import { useGenreId, useHero } from "../hooks";
import HeroBillboard from "../components/HeroBillboard";
import Rail from "../components/Rail";
import GenreMenu from "../components/GenreMenu";

export default function Shows() {
  const hero = useHero("series");
  const actionId = useGenreId("Action & Adventure");
  const [picks, setPicks] = useState([]);
  const [popular, setPopular] = useState([]);
  const [fresh, setFresh] = useState([]);
  const [action, setAction] = useState([]);

  useEffect(() => {
    api("/api/titles?kind=series").then((r) => {
      if (!r.ok) return;
      const s = [...unwrapItems(r)].sort((a, b) => (b.rating || 0) - (a.rating || 0));
      setPicks(s.slice(0, 12));
    });
    api("/api/titles?kind=series&year=2026").then((r) => {
      if (r.ok) setFresh(unwrapItems(r));
    });
  }, []);
  useEffect(() => {
    if (actionId == null) return;
    api(`/api/genres/${actionId}/titles`).then((r) => {
      if (r.ok) setAction(unwrapItems(r).filter((t) => t.kind === "series"));
    });
  }, [actionId]);
  useEffect(() => {
    api("/api/titles/trending").then((r) => {
      if (r.ok) setPopular(unwrapItems(r).filter((t) => t.kind === "series").slice(0, 12));
    });
  }, []);

  return (
    <div className="pt-0 pb-10">
      {hero && <HeroBillboard title={hero} />}
      <div className="relative z-10 -mt-10 md:-mt-16">
        <div className="px-4 md:px-[4vw] mb-2 flex items-center gap-3">
          <h2 className="text-lg md:text-xl font-semibold">TV Shows</h2>
          <GenreMenu />
        </div>
        <Rail title="Today's Top Picks for You" items={picks} />
        <Rail title="Popular TV Shows" items={popular} />
        <Rail title="TV Action & Adventure" items={action} titleLink={actionId ? `/browse/genre/${actionId}` : null} />
        <Rail title="New TV Shows on Netflix" items={fresh} titleLink="/new" />
      </div>
    </div>
  );
}
