import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, unwrapItems } from "../api";
import { openTitleModal } from "../App";

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

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

  const hero = titles[0];
  if (!loaded) {
    return <div className="min-h-screen bg-nfg" />;
  }

  return (
    <div className="pt-0 pb-10">
      {hero && (
        <div className="relative w-full h-[78vh] min-h-[560px]">
          <img
            src={hero.backdrop || hero.poster}
            alt={hero.name}
            className="absolute inset-0 w-full h-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-black/85 via-black/35 to-transparent" />
          <div className="absolute inset-x-0 bottom-0 h-[8vh] bg-gradient-to-t from-[#141414] to-transparent" />
          <div className="absolute top-[7vh] left-[8.3vw]">
            <h1 className="font-display text-[1.6vw] leading-tight uppercase tracking-wide drop-shadow-lg">
              {genre ? genre.name : "…"}
            </h1>
          </div>
          <div className="absolute bottom-[11vh] left-[2.6vw] max-w-[42vw]">
            <h2 className="font-display text-[1.5vw] leading-[1.1] uppercase drop-shadow-lg">
              {hero.name}
            </h2>
            <div className="mt-[1.2vh] flex items-center gap-3 text-[13px]">
              {hero.rating != null && (
                <span className="text-[#46d369] font-semibold">{Math.round(hero.rating * 10)}% Match</span>
              )}
              {hero.year && <span className="text-[#e5e5e5]">{hero.year}</span>}
              {hero.kind === "series" && <span className="text-[#e5e5e5]">Series</span>}
              {hero.kind === "movie" && fmtDuration(hero.duration) && (
                <span className="text-[#e5e5e5]">{fmtDuration(hero.duration)}</span>
              )}
              {hero.maturity_rating && (
                <span className="border border-[#6d6d6e] pl-1.5 pr-1 py-px text-[11px]">{hero.maturity_rating}</span>
              )}
            </div>
            <div className="mt-[2vh] flex items-center gap-3">
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
        <div className="px-[3.33vw] mt-[0.5vh]">
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
                </button>
                <div className="mt-1.5 text-[13px] truncate">{t.name}</div>
                <div className="text-[11px] text-[#707070]">
                  {t.kind === "movie" ? "Movie" : "Series"} · {t.year}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
