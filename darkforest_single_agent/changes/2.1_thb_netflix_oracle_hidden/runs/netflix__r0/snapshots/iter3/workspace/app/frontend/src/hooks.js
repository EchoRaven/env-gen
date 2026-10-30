import { useEffect, useState } from 'react';
import { useStore } from './store';

// Fetch helper: re-runs when deps or the active profile change. Returns null while loading.
export function useApi(fn, deps = []) {
  const { profile } = useStore();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    fn().then((d) => alive && setData(d)).catch((e) => { if (alive) { setError(e); setData([]); } });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.id, ...deps]);
  return [data, error];
}
