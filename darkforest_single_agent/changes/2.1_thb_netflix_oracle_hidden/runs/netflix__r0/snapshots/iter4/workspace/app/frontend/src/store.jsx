import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { API, session, setUnauthorizedHandler } from './api';

const Ctx = createContext(null);

export function StoreProvider({ children }) {
  const [token, setToken] = useState(session.token);
  const [profile, setProfile] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [profilesLoaded, setProfilesLoaded] = useState(false);
  const [myList, setMyList] = useState(new Set());
  const [ratings, setRatings] = useState({});
  const [listVersion, setListVersion] = useState(0);
  const [toast, setToast] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => { setRefreshKey((k) => k + 1); window.scrollTo({ top: 0 }); }, []);

  const logout = useCallback(() => {
    session.token = null;
    session.profileId = null;
    setToken(null);
    setProfile(null);
    setProfiles([]);
    setProfilesLoaded(false);
    setMyList(new Set());
    setRatings({});
  }, []);

  useEffect(() => { setUnauthorizedHandler(logout); }, [logout]);

  const loadProfiles = useCallback(async () => {
    const list = await API.profiles();
    setProfiles(list);
    setProfilesLoaded(true);
    const current = list.find((p) => String(p.id) === session.profileId);
    setProfile(current || null);
    if (!current) session.profileId = null;
    return list;
  }, []);

  useEffect(() => { if (token) loadProfiles().catch(() => setProfilesLoaded(true)); }, [token, loadProfiles]);

  const loadLibrary = useCallback(async () => {
    const [list, rs] = await Promise.all([API.myList(), API.ratings()]);
    setMyList(new Set(list.map((x) => x.title_id)));
    setRatings(Object.fromEntries(rs.map((r) => [r.title_id, r.value])));
  }, []);

  useEffect(() => {
    if (token && profile) loadLibrary().catch(() => {});
  }, [token, profile, loadLibrary]);

  const signIn = useCallback((accessToken) => {
    session.token = accessToken;
    session.profileId = null;
    setToken(accessToken);
  }, []);

  const selectProfile = useCallback((p) => {
    session.profileId = p ? p.id : null;
    setProfile(p);
  }, []);

  const showToast = useCallback((msg) => {
    setToast(msg);
    clearTimeout(window.__nfToast);
    window.__nfToast = setTimeout(() => setToast(null), 2500);
  }, []);

  const toggleMyList = useCallback(async (title) => {
    const id = title.id;
    if (myList.has(id)) {
      await API.removeMyList(id);
      setMyList((s) => { const n = new Set(s); n.delete(id); return n; });
      showToast(`Removed “${title.name}” from My List`);
    } else {
      await API.addMyList(id);
      setMyList((s) => new Set(s).add(id));
      showToast(`Added “${title.name}” to My List`);
    }
    setListVersion((v) => v + 1);
  }, [myList, showToast]);

  const rate = useCallback(async (title, value) => {
    const current = ratings[title.id];
    const next = current === value ? 0 : value;
    await API.rate(title.id, next);
    setRatings((r) => { const n = { ...r }; if (next) n[title.id] = next; else delete n[title.id]; return n; });
    return next;
  }, [ratings]);

  const value = useMemo(() => ({
    token, profile, profiles, profilesLoaded, myList, ratings, listVersion, toast, refreshKey, refresh,
    signIn, logout, selectProfile, loadProfiles, toggleMyList, rate, showToast,
  }), [token, profile, profiles, profilesLoaded, myList, ratings, listVersion, toast, refreshKey, refresh, signIn, logout, selectProfile, loadProfiles, toggleMyList, rate, showToast]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useStore = () => useContext(Ctx);
