import { useEffect, useRef, useState } from "react";
import { api, unwrapItems } from "../api";
import { openTitleModal } from "../App";

export default function SearchOverlay({ onClose }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null); // null = not searched yet
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current && inputRef.current.focus();
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    const t = setTimeout(async () => {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}`);
      if (r.ok) setResults(unwrapItems(r));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="absolute top-[68px] left-0 right-0 bg-[#181818]/95 border-b border-[#333] px-4 md:px-[4vw] py-6">
      <div className="flex items-center gap-3 mb-5">
        <img src="/assets/icons/search.svg" alt="" className="w-5 h-5 invert" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Titles, genres"
          className="flex-1 bg-transparent outline-none text-lg placeholder-[#666]"
        />
      </div>
      {q.trim() ? (
        results && results.length ? (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {results.map((t) => (
              <button
                key={t.id}
                onClick={() => { onClose(); openTitleModal(t.id); }}
                className="text-left group"
              >
                <div className="aspect-video rounded overflow-hidden bg-[#222]">
                  <img
                    src={t.backdrop || t.poster}
                    alt={t.name}
                    className="w-full h-full object-cover group-hover:opacity-80"
                    loading="lazy"
                  />
                </div>
                <div className="mt-1.5 text-[13px] text-[#e5e5e5] line-clamp-2">{t.name}</div>
              </button>
            ))}
          </div>
        ) : (
          <div className="text-[#999]">No results found for “{q}”</div>
        )
      ) : (
        <div className="text-[#999]">Search for movies, series and more. Start typing to search.</div>
      )}
    </div>
  );
}
