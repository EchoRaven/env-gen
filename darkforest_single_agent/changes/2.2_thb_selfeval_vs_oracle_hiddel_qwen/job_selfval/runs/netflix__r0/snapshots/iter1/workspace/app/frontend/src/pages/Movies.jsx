import { useEffect, useState } from "react";
import { api, unwrapItems } from "../api";
import { useGenreId, useHero } from "../hooks";
import HeroBillboard from "../components/HeroBillboard";
import Rail from "../components/Rail";
import GenreMenu from "../components/GenreMenu";

export default function Movies() {
  const hero = useHero("movie");
  const dramaId = useGenreId("Drama");
  const [picks, setPicks] = useState([]);
  const [popular, setPopular] = useState([]);
  const [fresh, setFresh] = useState([]);
  const [drama, setDrama] = useState([]);

  useEffect(() => {
    api("/api/titles?kind=movie").then((r) => {
      if (!r.ok) return;
      const m = [...unwrapItems(r)].sort((a, b) => (b.rating || 0) - (a.rating || 0));
      setPicks(m.slice(0, 12));
    });
    api("/api/titles?kind=movie&year=2026").then((r) => {
      if (r.ok) setFresh(unwrapItems(r));
    });
    api("/api/titles/trending").then((r) => {
      if (r.ok) setPopular(unwrapItems(r).filter((t) => t.kind === "movie").slice(0, 12));
    });
  }, []);
  useEffect(() => {
    if (dramaId == null) return;
    api(`/api/genres/${dramaId}/titles`).then((r) => {
      if (r.ok) setDrama(unwrapItems(r).filter((t) => t.kind === "movie"));
    });
  }, [dramaId]);

  return (
    <div className="pt-0 pb-10">
      {hero && <HeroBillboard title={hero} />}
      <div className="relative z-10 -mt-10 md:-mt-16">
        <div className="px-4 md:px-[4vw] mb-2 flex items-center gap-3">
          <h2 className="text-lg md:text-xl font-semibold">Movies</h2>
          <GenreMenu />
        </div>
        <Rail title="Gems for You" items={picks} />
        <Rail title="Popular Movies" items={popular} />
        <Rail title="Drama Movies" items={drama} titleLink={dramaId ? `/browse/genre/${dramaId}` : null} />
        <Rail title="New Movies on Netflix" items={fresh} titleLink="/new" />
      </div>
    </div>
  );
}
