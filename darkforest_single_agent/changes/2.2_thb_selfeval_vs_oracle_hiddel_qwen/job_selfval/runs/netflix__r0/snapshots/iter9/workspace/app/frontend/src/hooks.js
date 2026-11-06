import { useEffect, useState } from "react";
import { api, unwrapItems } from "./api";

export function useList(path, deps = []) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setLoading(true);
    api(path).then((r) => {
      if (!live) return;
      setLoading(false);
      if (r.ok) setItems(unwrapItems(r));
      else setError(r.data.detail || "Failed to load");
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  return { items, loading, error };
}

// Resolve a genre id by its exact name (null until resolved).
export function useGenreId(name) {
  const [id, setId] = useState(null);
  useEffect(() => {
    api("/api/genres").then((r) => {
      if (!r.ok) return;
      const g = unwrapItems(r).find((x) => x.name === name);
      if (g) setId(g.id);
    });
  }, [name]);
  return id;
}

// Pick a featured (hero) title: top10 of `kind`, or first trending.
export function useHero(kind) {
  const [hero, setHero] = useState(null);
  useEffect(() => {
    let live = true;
    api(`/api/titles/top10${kind ? `?kind=${kind}` : ""}`).then((r) => {
      if (!live) return;
      if (r.ok && r.data.items?.length) setHero(r.data.items[0]);
      else api("/api/titles/trending").then((t) => {
        if (live && t.ok && t.data.items?.length) setHero(t.data.items[0]);
      });
    });
    return () => { live = false; };
  }, [kind]);
  return hero;
}
