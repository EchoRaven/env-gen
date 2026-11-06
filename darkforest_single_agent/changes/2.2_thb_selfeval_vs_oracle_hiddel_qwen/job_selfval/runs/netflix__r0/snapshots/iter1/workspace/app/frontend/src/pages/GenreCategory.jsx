import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, unwrapItems } from "../api";
import HeroBillboard from "../components/HeroBillboard";
import Rail from "../components/Rail";

export default function GenreCategory() {
  const { genreId } = useParams();
  const [genre, setGenre] = useState(null);
  const [titles, setTitles] = useState([]);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let live = true;
    setGenre(null);
    setNotFound(false);
    api("/api/genres").then((g) => {
      if (!live || !g.ok) return;
      const row = unwrapItems(g).find((x) => x.id === parseInt(genreId, 10));
      if (!row) {
        setNotFound(true);
        return;
      }
      setGenre(row);
      api(`/api/genres/${row.id}/titles`).then((r) => {
        if (live && r.ok) setTitles(unwrapItems(r));
      });
    });
    return () => { live = false; };
  }, [genreId]);

  if (notFound) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center pt-[68px] text-[#999]">
        <div className="text-2xl mb-2">Genre not found</div>
        <a href="/browse" className="text-[#53c1de] hover:underline">Back to Home</a>
      </div>
    );
  }

  const hero = titles[0];
  const series = titles.filter((t) => t.kind === "series");
  const movies = titles.filter((t) => t.kind === "movie");

  return (
    <div className="pt-0 pb-10">
      {hero && <HeroBillboard title={hero} tall={false} />}
      <div className="relative z-10 -mt-8 md:-mt-10">
        <div className="px-4 md:px-[4vw] mb-2">
          <h2 className="text-lg md:text-xl font-semibold">{genre ? genre.name : "…"}</h2>
        </div>
        <Rail title={`Top Picks in ${genre ? genre.name : ""}`} items={titles} />
        {series.length > 0 && <Rail title={`${genre ? genre.name : ""} TV Shows`} items={series} />}
        {movies.length > 0 && <Rail title={`${genre ? genre.name : ""} Movies`} items={movies} />}
      </div>
    </div>
  );
}
