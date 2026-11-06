import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, unwrapItems } from "../api";
import { openTitleModal } from "../App";

export default function GenreCategory() {
  const { genreId } = useParams();
  const nav = useNavigate();
  const [genre, setGenre] = useState(null);
  const [titles, setTitles] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let live = true;
    setGenre(null);
    setTitles([]);
    setLoaded(false);
    setNotFound(false);
    api("/api/genres").then((g) => {
      if (!live || !g.ok) return;
      const row = unwrapItems(g).find((x) => x.id === parseInt(genreId, 10));
      if (!row) {
        setNotFound(true);
        setLoaded(true);
        return;
      }
      setGenre(row);
      api(`/api/genres/${row.id}/titles`).then((r) => {
        if (!live) return;
        setTitles(r.ok ? unwrapItems(r) : []);
        setLoaded(true);
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

  if (!loaded) {
    return <div className="min-h-screen bg-nfg" />;
  }

  const hero = titles[0];
  const byYear = [...titles].sort((a, b) => (b.year || 0) - (a.year || 0));
  const freshIds = new Set(byYear.slice(0, 4).map((t) => t.id));

  return (
    <div className="pt-0 pb-10">
      {hero && (
        <div className="relative w-full h-[73vh] min-h-[520px]">
          <img
            src={hero.backdrop || hero.poster}
            alt={hero.name}
            className="absolute inset-0 w-full h-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-black/85 via-black/35 to-transparent" />
          <div className="absolute inset-x-0 bottom-0 h-[8vh] bg-gradient-to-t from-[#141414] to-transparent" />
          <div className="absolute top-[44.5vh] left-[3.6vw] max-w-[46vw]">
            <div className="text-[#e50914] font-bold tracking-[0.08em] uppercase text-[1.25vw] leading-none">
              Genres
            </div>
            <h1
              className={`mt-[2.4vh] font-display leading-[1.02] text-white drop-shadow-lg ${
                (genre ? genre.name.length : 0) > 12 ? "text-[4vw]" : "text-[6.7vw]"
              }`}
            >
              {genre ? genre.name : ""}
            </h1>
            <div className="mt-[6.5vh] flex items-center gap-3">
              <button
                onClick={() => nav(`/watch/${hero.id}`)}
                className="flex items-center gap-2.5 bg-white text-black font-semibold rounded px-[2.2vw] py-[0.55vw] hover:bg-white/80 transition-colors"
              >
                <img src="/assets/icons/play.svg" alt="" className="w-6 h-6" />
                Play
              </button>
              <button
                onClick={() => openTitleModal(hero.id)}
                className="flex items-center gap-2.5 bg-[#6d6d6e]/50 text-white font-semibold rounded px-[1.9vw] py-[0.55vw] hover:bg-[#6d6d6e]/35 transition-colors backdrop-blur-sm"
              >
                <img src="/assets/icons/info.svg" alt="" className="w-6 h-6 invert" />
                More Info
              </button>
            </div>
          </div>
        </div>
      )}
      {titles.length === 0 ? (
        <div className="px-[3.5vw] pt-[8vh] text-[#999]">
          No titles found in this genre yet.
        </div>
      ) : (
        <div className="px-[3.33vw] mt-[1vh]">
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-1.5">
            {titles.map((t, i) => (
              <div key={t.id + "-" + i} className="group">
                <button
                  onClick={() => openTitleModal(t.id)}
                  className="w-full aspect-video rounded overflow-hidden bg-[#1f1f1f] relative block"
                >
                  <img
                    src={t.backdrop || t.poster}
                    alt={t.name}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
                  {t.top10_rank ? (
                    <div className="absolute top-1.5 right-1.5 bg-[#e50914] text-white rounded px-1.5 py-0.5 text-center leading-tight">
                      <div className="text-[8px] font-semibold tracking-wider">TOP</div>
                      <div className="text-[11px] font-bold">{t.top10_rank}</div>
                    </div>
                  ) : null}
                  {!t.top10_rank && freshIds.has(t.id) ? (
                    <div className="absolute bottom-1.5 inset-x-0 flex justify-center">
                      <span className="bg-[#e50914] text-white text-[10px] font-semibold tracking-wide rounded px-2 py-0.5">
                        NEW
                      </span>
                    </div>
                  ) : null}
                </button>
                <div className="mt-1.5 text-[13px] truncate">{t.name}</div>
                <div className="text-[11px] text-[#707070]">
                  {t.kind === "movie" ? "Movie" : "Series"}{t.year ? ` · ${t.year}` : ""}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
