import { useEffect, useState, useCallback } from "react";
import { api, unwrapItems } from "../api";
import { openTitleModal } from "../App";

export default function MyList() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    api("/api/my-list").then((r) => {
      setLoading(false);
      if (r.ok) setItems(unwrapItems(r));
    });
  }, []);

  useEffect(() => { load(); }, [load]);

  const remove = async (row) => {
    await api(`/api/my-list/${row.id}`, { method: "DELETE" });
    setItems((prev) => prev.filter((x) => x.id !== row.id));
  };

  return (
    <div className="pt-[96px] pb-10 px-[3.5vw] min-h-screen">
      <h1 className="text-[26px] font-semibold mb-[1.8vw]">My List</h1>
      {loading ? (
        <div className="text-[#999]">Loading…</div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <img src="/assets/icons/plus.svg" alt="" className="w-10 h-10 invert opacity-40 mb-4" />
          <div className="text-lg text-[#e5e5e5]">Your list is empty</div>
          <p className="mt-1 text-sm text-[#707070] max-w-md">
            Add shows and movies to keep track of everything you want to watch.
            Tap the + button on any title to add it here.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
          {items.map((t) => (
            <div key={t.id} className="group relative">
              <button
                onClick={() => openTitleModal(t.title_id)}
                className="w-full aspect-[9/8] rounded overflow-hidden bg-[#1f1f1f] relative block"
              >
                <img src={t.poster || t.backdrop} alt={t.name} className="w-full h-full object-cover" loading="lazy" />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
              </button>
              <button
                onClick={() => remove(t)}
                aria-label={`Remove ${t.name} from My List`}
                className="absolute top-2 right-2 w-8 h-8 rounded-full bg-black/70 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black z-10"
              >
                <img src="/assets/icons/x.svg" alt="" className="w-4 h-4 invert" />
              </button>
              <div className="mt-1.5 text-[13px] truncate">{t.name}</div>
              <div className="text-[11px] text-[#707070]">
                {t.kind === "movie" ? "Movie" : "Series"} · {t.year}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
