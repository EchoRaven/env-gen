import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, unwrapItem, unwrapItems } from "../api";
import { openTitleModal } from "../App";

const MOODS = {
  Comedy: "Charming",
  Drama: "Gripping",
  Action: "Intense",
  "Sci-Fi": "Mind-Bending",
  "Science Fiction": "Mind-Bending",
  Horror: "Chilling",
  Romance: "Sweeping",
  Documentary: "Eye-Opening",
  Crime: "Tense",
  Adventure: "Sweeping"
};

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

export default function TitleDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [title, setTitle] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [eps, setEps] = useState([]);
  const [season, setSeason] = useState(1);
  const [top10, setTop10] = useState([]);
  const [all, setAll] = useState([]);

  useEffect(() => {
    setTitle(null);
    setNotFound(false);
    setEps([]);
    setSeason(1);
    window.scrollTo(0, 0);
    api(`/api/titles/${id}`).then((r) => {
      if (!r.ok) setNotFound(true);
      else setTitle(unwrapItem(r));
    });
    api(`/api/titles/${id}/episodes`).then((r) => setEps(unwrapItems(r)));
    api("/api/titles/top10").then((r) => setTop10(unwrapItems(r)));
    api("/api/titles").then((r) => setAll(unwrapItems(r)));
  }, [id]);

  if (notFound) {
    return (
      <div className="min-h-screen bg-nfg flex flex-col items-center justify-center gap-4">
        <p className="text-[20px] text-[#e5e5e5]">We couldn't find that title.</p>
        <Link to="/browse" className="text-[14px] font-semibold text-white bg-[#e50914] rounded px-6 py-3">
          Back to Browse
        </Link>
      </div>
    );
  }

  if (!title) return <div className="min-h-screen bg-nfg" />;

  const seasons = [...new Set(eps.map((e) => e.season))].sort((a, b) => a - b);
  const seasonEps = eps.filter((e) => e.season === season);
  const genres = title.genres || (title.genre ? [title.genre] : []);
  const mood = MOODS[genres[0]] || "Binge-Worthy";
  const metaLine =
    title.kind === "series"
      ? `${title.year} · ${seasons.length || 1} ${seasons.length === 1 ? "Season" : "Seasons"} · HD`
      : `${title.year} · ${fmtDuration(title.duration)} · HD`;

  return (
    <div className="min-h-screen bg-nfg">
      {/* hero billboard */}
      <div className="relative h-[64vh]">
        <img
          src={title.backdrop || title.poster}
          alt={title.name}
          className="absolute inset-0 w-full h-full object-cover object-top"
        />
        <div className="absolute inset-x-0 bottom-0 h-[35vh] bg-gradient-to-b from-transparent to-nfg" />
        <div className="absolute left-[9.9vw] top-[10vh] text-[24px] font-semibold text-white">
          {title.genre}
        </div>
        <h1 className="absolute left-[24.8vw] top-[36.5vh] font-display uppercase leading-none text-[#e50914] text-[68px]">
          {title.name}
        </h1>
        <button
          onClick={() => nav(`/watch/${title.id}`)}
          className="absolute left-[28.5vw] top-[48.5vh] flex items-center gap-2.5 bg-white text-[#141414] font-semibold text-[16px] rounded px-[26px] h-[46px] hover:bg-white/85 transition-colors"
        >
          <img src="/assets/icons/play.svg" alt="" className="w-5 h-5" />
          Play
        </button>
      </div>

      {/* content grid */}
      <div className="relative z-10 -mt-[16vh] px-[3.4vw] flex gap-[2.8vw]">
        {/* left rail */}
        <div className="w-[18.2vw] shrink-0 flex flex-col">
          <img
            src={title.poster || title.backdrop}
            alt={title.name}
            className="w-[16.5vw] aspect-[2/3] object-cover rounded shadow-2xl"
          />
          <div className="mt-5 flex items-center gap-2 text-[15px] text-white">
            <span>
              {title.genre} {title.year}
              {title.kind === "series"
                ? ` · ${seasons.length || 1} ${seasons.length === 1 ? "Episode" : "Episodes"}`
                : ""}
            </span>
            {title.maturity_rating && (
              <span className="border border-[#6d6d6e] px-1.5 text-[12px]">{title.maturity_rating}</span>
            )}
          </div>
          <p className="mt-3 text-[14px] leading-relaxed text-[#b3b3b3] line-clamp-4">
            {title.synopsis}
          </p>
          <div className="mt-5 flex gap-3">
            <button
              onClick={() => nav(`/watch/${title.id}`)}
              className="flex items-center gap-2 bg-white text-[#141414] font-semibold text-[15px] rounded px-6 py-2.5 hover:bg-white/85 transition-colors"
            >
              <img src="/assets/icons/play.svg" alt="" className="w-4 h-4" />
              Play
            </button>
            <button
              onClick={() => openTitleModal(title.id)}
              className="bg-[#636367]/60 text-white font-medium text-[15px] rounded px-6 py-2.5 hover:bg-[#636367]/80 transition-colors"
            >
              More Info
            </button>
          </div>
          <Link to="/games" className="mt-12 flex items-center gap-2">
            <span className="text-[22px] font-bold text-white">Games</span>
            <span className="bg-[#e50914] text-white text-[11px] font-bold px-1.5 py-0.5 rounded">
              BETA
            </span>
          </Link>
        </div>

        {/* main column */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-8">
            <div className="text-[17px] text-white">{metaLine}</div>
            <div className="w-[340px] shrink-0 space-y-2.5 text-[14px] text-[#e5e5e5]">
              {genres.length > 0 && (
                <div>
                  <span className="text-[#707070]">Genres: </span>
                  {genres.join(", ")}
                </div>
              )}
              <div>
                <span className="text-[#707070]">This Show Is: </span>
                {mood}
              </div>
              <div className="flex flex-wrap gap-2 pt-1">
                {genres.slice(0, 3).map((g) => (
                  <Link
                    key={g}
                    to={`/browse/genre/${encodeURIComponent(g)}`}
                    className="border border-[#4d4d4d] rounded-full px-3 py-1 text-[12px] text-[#e5e5e5] hover:border-white hover:text-white transition-colors"
                  >
                    {g}
                  </Link>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-4 flex items-center gap-3">
            {title.maturity_rating && (
              <span className="border border-[#6d6d6e] px-1.5 text-[12px] text-[#e5e5e5]">
                {title.maturity_rating}
              </span>
            )}
            {title.rating != null && (
              <span className="text-[14px] text-[#46d369] font-semibold">
                {Math.round(title.rating * 10)}% Match
              </span>
            )}
          </div>

          <p className="mt-6 max-w-[62vw] text-[15px] leading-relaxed text-[#e5e5e5]">
            {title.synopsis}
          </p>

          {eps.length > 0 && (
            <div className="mt-12">
              <div className="flex items-center justify-between">
                <h2 className="text-[22px] font-semibold text-white">Episodes</h2>
                <select
                  value={season}
                  onChange={(e) => setSeason(Number(e.target.value))}
                  className="bg-[#2f2f2f] border-0 rounded px-3 py-1.5 text-[14px] text-white outline-none"
                  aria-label="Season"
                >
                  {seasons.map((s) => (
                    <option key={s} value={s}>
                      Season {s}
                    </option>
                  ))}
                </select>
              </div>
              <div className="mt-5 space-y-6">
                {seasonEps.map((e) => (
                  <div key={e.id} className="flex gap-[2vw]">
                    <button
                      onClick={() => nav(`/watch/${title.id}`)}
                      aria-label={`Play ${e.name}`}
                      className="relative w-[13.2vw] aspect-video shrink-0 rounded overflow-hidden group"
                    >
                      <img
                        src={e.thumbnail || title.backdrop}
                        alt={e.name}
                        className="w-full h-full object-cover"
                      />
                      <span className="absolute inset-0 bg-black/30 group-hover:bg-black/10 transition-colors flex items-center justify-center">
                        <img src="/assets/icons/play.svg" alt="" className="w-7 h-7 invert" />
                      </span>
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline justify-between gap-4">
                        <span className="text-[15px] text-white truncate">
                          {e.number}. {e.name}
                        </span>
                        <span className="text-[13px] text-[#b3b3b3] shrink-0">
                          {fmtDuration(e.duration)}
                        </span>
                      </div>
                      <p className="mt-1.5 pr-[13vw] text-[14px] leading-relaxed text-[#b3b3b3]">
                        {e.synopsis}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {eps.length === 0 && (
            <p className="mt-10 text-[14px] text-[#707070]">No episodes for this title yet.</p>
          )}
        </div>

        {/* right column */}
        <div className="w-[14.5vw] shrink-0 flex gap-[1.2vw] pt-1">
          <div className="w-1/2 min-w-0">
            <div className="text-[13px] font-semibold text-white mb-2">Recently Added</div>
            {all.filter((t) => t.id !== title.id).slice(0, 4).map((t) => (
              <Link key={t.id} to={`/title/${t.id}`} className="block mb-2.5 group">
                <img
                  src={t.backdrop || t.poster}
                  alt={t.name}
                  className="w-full aspect-video object-cover rounded group-hover:opacity-80 transition-opacity"
                />
                <span className="text-[11px] text-[#b3b3b3] mt-1 block truncate">{t.name}</span>
              </Link>
            ))}
            {all.length <= 1 && (
              <p className="text-[11px] text-[#707070]">Nothing added yet.</p>
            )}
          </div>
          <div className="w-1/2 min-w-0">
            <div className="text-[13px] font-semibold text-white mb-2">#1 in TV Shows</div>
            {top10.slice(0, 5).map((t) => (
              <Link key={t.id} to={`/title/${t.id}`} className="flex gap-2 mb-2.5 group">
                <span className="font-display text-[20px] leading-none text-[#e50914] w-6 shrink-0">
                  {t.top10_rank}
                </span>
                <span className="text-[12px] leading-tight text-[#e5e5e5] group-hover:text-white transition-colors">
                  {t.name}
                </span>
              </Link>
            ))}
            {top10.length === 0 && (
              <p className="text-[11px] text-[#707070]">No Top 10 titles yet.</p>
            )}
          </div>
        </div>
      </div>

      <footer className="px-[0.5vw] mt-10 pb-5">
        <Link to="/" className="text-[12px] text-[#6d6d6e] hover:text-[#999]">
          https://www.netflix.com
        </Link>
      </footer>
    </div>
  );
}
