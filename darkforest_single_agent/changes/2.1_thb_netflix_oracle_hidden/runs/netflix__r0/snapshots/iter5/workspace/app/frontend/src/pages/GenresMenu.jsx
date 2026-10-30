import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

export default function GenresMenu({ genres, kind }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);
  return (
    <div className="genres-menu" ref={ref}>
      <button className="genres-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu">
        Genres <span className="tri" />
      </button>
      {open && (
        <div className="genres-list" role="menu">
          {(genres || []).length === 0 && <span className="muted">—</span>}
          {(genres || []).map((g) => (
            <Link key={g.id} role="menuitem" to={`/browse/genre/${g.id}?kind=${kind}`} onClick={() => setOpen(false)}>{g.name}</Link>
          ))}
        </div>
      )}
    </div>
  );
}
