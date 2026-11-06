import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, unwrapItems } from "../api";

export default function GenreMenu() {
  const [open, setOpen] = useState(false);
  const [genres, setGenres] = useState([]);
  const ref = useRef(null);
  const nav = useNavigate();

  useEffect(() => {
    api("/api/genres").then((r) => {
      if (r.ok) setGenres(unwrapItems(r));
    });
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[15px] md:text-[17px] font-semibold border border-[#6d6d6e] rounded px-3 py-1 hover:border-white"
      >
        Genres
        <img src="/assets/icons/chevron-down.svg" alt="" className="w-3.5 h-3.5 invert" />
      </button>
      {open && (
        <div className="absolute z-30 top-full mt-2 w-64 max-h-80 overflow-y-auto bg-[#181818] border border-[#333] shadow-xl">
          {genres.map((g) => (
            <button
              key={g.id}
              onClick={() => { setOpen(false); nav(`/browse/genre/${g.id}`); }}
              className="w-full text-left px-4 py-2 text-sm hover:bg-[#2a2a2a]"
            >
              {g.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
