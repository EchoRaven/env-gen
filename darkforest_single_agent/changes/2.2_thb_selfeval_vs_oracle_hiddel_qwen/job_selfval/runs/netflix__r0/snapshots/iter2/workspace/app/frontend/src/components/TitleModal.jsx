import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, unwrapItems } from "../api";

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

export default function TitleModal({ id, onClose }) {
  const nav = useNavigate();
  const [title, setTitle] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [season, setSeason] = useState(1);
  const [inList, setInList] = useState(null);
  const [rating, setRating] = useState(null);

  useEffect(() => {
    let live = true;
    api(`/api/titles/${id}`).then((r) => {
      if (live && r.ok) setTitle(r.data.item);
    });
    return () => { live = false; };
  }, [id]);

  useEffect(() => {
    if (!title || title.kind !== "series") return;
    api(`/api/titles/${id}/episodes`).then((r) => {
      if (r.ok) setEpisodes(r.data.items || []);
    });
  }, [id, title && title.kind]);

  const seasons = useMemo(
    () => [...new Set(episodes.map((e) => e.season))].sort((a, b) => a - b),
    [episodes]
  );
  const eps = episodes
    .filter((e) => e.season === (seasons.length ? season : 1))
    .sort((a, b) => a.number - b.number);

  const checkList = async () => {
    const r = await api("/api/my-list");
    if (r.ok) setInList(unwrapItems(r).some((m) => m.title_id === id));
  };
  useEffect(() => {
    checkList();
    api("/api/ratings").then((r) => {
      if (r.ok) {
        const row = unwrapItems(r).find((x) => x.title_id === id);
        setRating(row ? row.value : null);
      }
    });
  }, [id]);

  const toggleList = async () => {
    if (inList === null) await checkList();
    if (inList) {
      const r = await api("/api/my-list");
      const row = unwrapItems(r).find((m) => m.title_id === id);
      if (row) await api(`/api/my-list/${row.id}`, { method: "DELETE" });
      setInList(false);
    } else {
      await api("/api/my-list", { method: "POST", body: { title_id: id } });
      setInList(true);
    }
  };

  if (!title) {
    return (
      <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center" onMouseDown={onClose}>
        <div className="text-[#999]">Loading…</div>
      </div>
    );
  }

  const img = title.backdrop || title.poster;

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-black/70"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full bg-[#141414] shadow-2xl relative pb-10">
        {/* backdrop hero */}
        <div className="relative h-[53vh] min-h-[420px]">
          <img src={img} alt={title.name} className="absolute inset-0 w-full h-full object-cover" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#141414] via-transparent to-black/30" />
          <button
            onClick={onClose}
            aria-label="Close"
            className="absolute top-4 right-4 w-10 h-10 rounded-full bg-black/60 border border-[#4d4d4d] flex items-center justify-center hover:bg-black/80"
          >
            <img src="/assets/icons/x.svg" alt="" className="w-5 h-5 invert" />
          </button>
          <div className="absolute bottom-[6%] left-[3.5vw] max-w-[70vw]">
            <h2 className="font-display text-[5.5vw] max-w-full leading-[1] uppercase drop-shadow-lg">
              {title.name}
            </h2>
          </div>
        </div>

        <div className="px-[3.5vw]">
          <div className="mt-[2.5vh] flex items-center gap-3">
            <button
              onClick={() => nav(`/watch/${title.id}`)}
              className="flex items-center gap-2.5 bg-white text-black font-semibold rounded px-7 py-2.5 hover:bg-white/80"
            >
              <img src="/assets/icons/play.svg" alt="" className="w-5 h-5" />
              Play
            </button>
            <button
              onClick={toggleList}
              aria-label={inList ? "Remove from My List" : "Add to My List"}
              className="w-12 h-12 rounded-full border-2 border-[#6d6d6e] flex items-center justify-center hover:border-white"
            >
              {inList === true ? (
                <img src="/assets/icons/check.svg" alt="" className="w-5 h-5 invert" />
              ) : (
                <img src="/assets/icons/plus.svg" alt="" className="w-5 h-5 invert" />
              )}
            </button>
            <button
              onClick={() => window.dispatchEvent(new CustomEvent("nf:rate", { detail: { id } }))}
              aria-label="Rate this title"
              className="w-12 h-12 rounded-full border-2 border-[#6d6d6e] flex items-center justify-center hover:border-white"
            >
              <img
                src={rating === 3 ? "/assets/icons/netflix/thumbs_up_two.svg" : "/assets/icons/thumbs-up.svg"}
                alt=""
                className="w-5 h-5 invert"
              />
            </button>
          </div>

          <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-6 pb-8">
            <div className="md:col-span-2 text-[15px] text-[#e5e5e5]">
              <div className="flex items-center gap-2.5 mb-2 text-[13px] flex-wrap">
                {title.rating != null && (
                  <span className="text-[#46d369] font-semibold">
                    {Math.round(title.rating * 10)}% Match
                  </span>
                )}
                {title.year && <span>{title.year}</span>}
                {title.kind === "series" && seasons.length > 0 && (
                  <span>{seasons.length} Season{seasons.length > 1 ? "s" : ""}</span>
                )}
                {title.kind === "movie" && fmtDuration(title.duration) && (
                  <span>{fmtDuration(title.duration)}</span>
                )}
                <span className="border border-[#6d6d6e] px-1.5 text-[11px]">{title.maturity_rating}</span>
                <span className="border border-[#6d6d6e] px-1.5 text-[11px]">HD</span>
              </div>
              <p className="leading-relaxed">{title.synopsis}</p>
            </div>
            <div className="text-[13px] text-[#777] space-y-2.5">
              {title.genre && (
                <div>
                  <span className="text-[#777]">Genres: </span>
                  <span className="text-[#e5e5e5]">{(title.genres || [title.genre]).join(", ")}</span>
                </div>
              )}
              {title.language && (
                <div>
                  <span>Original Language: </span>
                  <span className="uppercase text-[#e5e5e5]">{title.language}</span>
                </div>
              )}
            </div>
          </div>

          {episodes.length > 0 && (
            <div className="border-t border-[#333] pt-4">
              <div className="flex items-center gap-4">
                <h3 className="text-[22px] font-semibold">Episodes</h3>
                {seasons.length > 1 && (
                  <select
                    value={season}
                    onChange={(e) => setSeason(parseInt(e.target.value, 10))}
                    aria-label="Season"
                    className="ml-auto bg-[#141414] border border-[#4d4d4d] rounded px-3 py-1.5 text-[14px]"
                  >
                    {seasons.map((s) => (
                      <option key={s} value={s}>
                        Season {s}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="mt-4 space-y-0 divide-y divide-[#2a2a2a]">
                {eps.map((e) => (
                  <div key={e.id} className="flex items-center gap-4 py-4">
                    <div className="flex flex-col items-center text-[13px] text-[#777] w-8 shrink-0">
                      {e.number}
                    </div>
                    <button
                      onClick={() => nav(`/watch/${title.id}?season=${e.season}&ep=${e.number}`)}
                      className="w-[15vw] min-w-[160px] aspect-video rounded overflow-hidden bg-[#1f1f1f] shrink-0 group"
                    >
                      <img
                        src={e.thumbnail || title.backdrop || title.poster}
                        alt={e.name}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-3">
                        <span className="font-semibold text-[15px] truncate">{e.name}</span>
                        <span className="ml-auto text-[13px] text-[#777] shrink-0">
                          {fmtDuration(e.duration)}
                        </span>
                      </div>
                      <p className="mt-1 text-[13px] text-[#999] line-clamp-2">{e.synopsis}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
