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
  const eps = episodes.filter((e) => e.season === (seasons.length ? season : 1));

  const checkList = async () => {
    const r = await api("/api/my-list");
    if (r.ok) setInList(unwrapItems(r).some((m) => m.title_id === id));
  };
  useEffect(() => { checkList(); api("/api/ratings").then((r) => {
    if (r.ok) {
      const row = unwrapItems(r).find((x) => x.title_id === id);
      setRating(row ? row.value : null);
    }
  }); }, [id]);

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
      className="fixed inset-0 z-50 overflow-y-auto bg-black/70 flex items-start justify-center py-6 md:py-10"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-[min(95vw,780px)] bg-[#181818] rounded-lg overflow-hidden shadow-2xl relative">
        <div className="relative">
          <img src={img} alt={title.name} className="w-full aspect-video object-cover" />
          <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-[#181818] to-transparent" />
          <button
            onClick={onClose}
            aria-label="Close"
            className="absolute top-3 right-3 w-9 h-9 rounded-full bg-[#181818] flex items-center justify-center hover:bg-[#2a2a2a]"
          >
            <img src="/assets/icons/x.svg" alt="" className="w-5 h-5 invert" />
          </button>
          <h2 className="absolute bottom-3 left-6 font-display text-3xl md:text-5xl uppercase drop-shadow">
            {title.name}
          </h2>
        </div>

        <div className="px-6 pb-6">
          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={() => nav(`/watch/${title.id}`)}
              className="flex items-center gap-2 bg-white text-black font-semibold rounded px-6 py-2 hover:bg-white/80"
            >
              <img src="/assets/icons/play.svg" alt="" className="w-5 h-5" />
              Play
            </button>
            <button
              onClick={toggleList}
              aria-label={inList ? "Remove from My List" : "Add to My List"}
              className="w-11 h-11 rounded-full border-2 border-[#6d6d6e] flex items-center justify-center hover:border-white"
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
              className="w-11 h-11 rounded-full border-2 border-[#6d6d6e] flex items-center justify-center hover:border-white"
            >
              <img
                src={rating === 3 ? "/assets/icons/netflix/thumbs_up_two.svg" : "/assets/icons/thumbs-up.svg"}
                alt=""
                className="w-5 h-5 invert"
              />
            </button>
          </div>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-2 text-sm text-[#e5e5e5]">
              <div className="flex items-center gap-2 mb-1.5 text-xs">
                {title.rating != null && (
                  <span className="text-[#46d369] font-semibold text-[13px]">
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
                <span className="border border-[#6d6d6e] px-1 text-[10px]">{title.maturity_rating}</span>
                <span className="border border-[#6d6d6e] px-1 text-[10px]">HD</span>
              </div>
              <p>{title.synopsis}</p>
            </div>
            <div className="text-xs text-[#777] space-y-2">
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

          {title.kind === "series" && (
            <div className="mt-6">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold">Episodes</h3>
                {seasons.length > 1 && (
                  <select
                    value={seasons.includes(season) ? season : seasons[0]}
                    onChange={(e) => setSeason(parseInt(e.target.value, 10))}
                    className="bg-[#2f2f2f] border border-[#4d4d4d] rounded px-2 py-1 text-sm"
                  >
                    {seasons.map((s) => (
                      <option key={s} value={s}>Season {s}</option>
                    ))}
                  </select>
                )}
              </div>
              {eps.length === 0 ? (
                <div className="text-sm text-[#777]">No episodes available for this title.</div>
              ) : (
                <div className="space-y-4">
                  {eps.map((e) => (
                    <button
                      key={e.id}
                      onClick={() => nav(`/watch/${title.id}?season=${e.season}&ep=${e.number}`)}
                      className="w-full flex gap-4 items-center bg-[#141414] hover:bg-[#232323] rounded p-3 text-left group/ep"
                    >
                      <span className="text-2xl text-[#555] w-6 text-center shrink-0">{e.number}</span>
                      <div className="w-32 aspect-video rounded overflow-hidden bg-[#222] shrink-0">
                        <img
                          src={e.thumbnail || title.backdrop || title.poster}
                          alt={e.name}
                          className="w-full h-full object-cover group-hover/ep:opacity-80"
                          loading="lazy"
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between gap-2">
                          <span className="font-medium truncate">{e.name}</span>
                          <span className="text-xs text-[#777] shrink-0">{fmtDuration(e.duration)}</span>
                        </div>
                        <p className="text-xs text-[#999] line-clamp-2 mt-1">{e.synopsis}</p>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
