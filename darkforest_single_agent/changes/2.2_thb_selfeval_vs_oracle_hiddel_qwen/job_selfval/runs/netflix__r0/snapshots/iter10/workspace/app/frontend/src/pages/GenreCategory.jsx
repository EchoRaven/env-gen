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

  const featured = [...titles].sort((a, b) => {
    const ar = a.top10_rank ? 0 : 1;
    const br = b.top10_rank ? 0 : 1;
    if (ar !== br) return ar - br;
    const av = a.top10_rank || 99;
    const bv = b.top10_rank || 99;
    if (av !== bv) return av - bv;
    return (b.rating || 0) - (a.rating || 0);
  })[0];
  const hero = featured || titles[0];
  const byYear = [...titles].sort((a, b) => (b.year || 0) - (a.year || 0));
  const freshIds = new Set(byYear.slice(0, 4).map((t) => t.id));
  const name = genre ? genre.name : "";
  const titleVw = name ? Math.min(5.8, 44 / (0.55 * name.length)) : 5.8;

  return (
    <div className="pt-0 pb-10">
      {hero && (
        <div className="relative w-full h-[77vh] min-h-[540px]">
          <img
            src={hero.backdrop || hero.poster}
            alt={hero.name}
            className="absolute inset-0 w-full h-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-black/85 via-black/35 to-transparent" />
          <div className="absolute inset-x-0 bottom-0 h-[8vh] bg-gradient-to-t from-[#141414] to-transparent" />
          {genre && (
            <div className="absolute top-[10.5vh] left-[3.6vw] text-[15px] text-[#e5e5e5]/75 tracking-wide">
              Browse <span className="text-[#6d6d6e] mx-1">/</span> {name}
            </div>
          )}
          <div className="absolute top-[38.5vh] left-[3.6vw] max-w-[52vw]">
            <h1
              className="font-display leading-[1.02] text-[#e50914] drop-shadow-lg"
              style={{ fontSize: `${titleVw}vw` }}
            >
              {name}
            </h1>
            {hero.synopsis ? (
              <p className="mt-[4.2vh] max-w-[42vw] text-[14px] leading-[1.5] text-[#e5e5e5] line-clamp-3 drop-shadow">
                {hero.synopsis}
              </p>
            ) : null}
            <div className="mt-[5vh] flex items-center gap-3">
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
