import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, getToken, setToken, getProfileId, setProfileId } from "./api";

const Ctx = createContext(null);

export function useApp() {
  return useContext(Ctx);
}

export function AppProvider({ children }) {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [booted, setBooted] = useState(false);

  const load = useCallback(async () => {
    if (!getToken()) {
      setBooted(true);
      return;
    }
    const r = await api("/api/profiles");
    if (r.status === 401 || r.status === 0) {
      setToken(null);
      setBooted(true);
      return;
    }
    const items = r.data.items || [];
    setProfiles(items);
    const me = await api("/api/me");
    if (me.ok && me.data.item) setUser(me.data.item);
    const saved = getProfileId();
    const prof = items.find((p) => String(p.id) === String(saved)) || items[0] || null;
    if (prof) {
      setProfile(prof);
      setProfileId(prof.id);
    }
    setBooted(true);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const login = useCallback(async (email, password) => {
    const r = await api("/auth/login", { method: "POST", body: { email, password } });
    if (!r.ok) return { ok: false, error: r.data.detail || "Sign in failed" };
    setToken(r.data.access_token);
    return { ok: true };
  }, []);

  const register = useCallback(async (email, password, name) => {
    const r = await api("/auth/register", {
      method: "POST",
      body: { email, password, name: name || email.split("@")[0] }
    });
    if (!r.ok) return { ok: false, error: r.data.detail || "Sign up failed" };
    setToken(r.data.access_token);
    return { ok: true };
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setProfileId(null);
    setUser(null);
    setProfile(null);
    setProfiles([]);
  }, []);

  const selectProfile = useCallback((p) => {
    setProfile(p);
    setProfileId(p.id);
  }, []);

  const refreshProfiles = useCallback(async () => {
    const r = await api("/api/profiles");
    if (r.ok) {
      const items = r.data.items || [];
      setProfiles(items);
      return items;
    }
    return profiles;
  }, [profiles]);

  return (
    <Ctx.Provider
      value={{
        user, profile, profiles, booted,
        login, register, logout, selectProfile, refreshProfiles, load
      }}
    >
      {children}
    </Ctx.Provider>
  );
}
