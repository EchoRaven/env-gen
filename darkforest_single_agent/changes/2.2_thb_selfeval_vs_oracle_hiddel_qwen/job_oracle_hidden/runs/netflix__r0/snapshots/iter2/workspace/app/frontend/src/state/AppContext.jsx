import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, getToken, getStoredUser, getStoredProfile, setSession, clearSession } from '../lib/api'

const Ctx = createContext(null)
export const useApp = () => useContext(Ctx)

export function AppProvider({ children }) {
  const [user, setUser] = useState(() => getStoredUser())
  const [profiles, setProfiles] = useState([])
  const [profile, setProfileState] = useState(() => getStoredProfile() ? { id: getStoredProfile() } : null)
  const [myListIds, setMyListIds] = useState(() => new Set())
  const [ratings, setRatings] = useState(() => ({}))
  const [ready, setReady] = useState(false)

  const refreshProfiles = useCallback(async () => {
    try {
      const list = await api('/api/profiles')
      setProfiles(list)
      return list
    } catch {
      return []
    }
  }, [])

  const refreshMyList = useCallback(async () => {
    const pid = getStoredProfile()
    if (pid == null) { setMyListIds(new Set()); return }
    try {
      const list = await api('/api/my-list')
      setMyListIds(new Set(list.map((t) => t.id)))
    } catch { setMyListIds(new Set()) }
  }, [])

  useEffect(() => {
    let alive = true
    async function boot() {
      const token = getToken()
      if (!token) { setReady(true); return }
      const stored = getStoredUser()
      if (stored) setUser(stored)
      const list = await refreshProfiles()
      if (!alive) return
      if (list.length === 0) {
        setReady(true)
        return
      }
      const storedProfile = getStoredProfile()
      const exists = storedProfile != null && list.some((p) => String(p.id) === String(storedProfile))
      const chosen = exists ? storedProfile : list[0].id
      setSession(null, null, chosen)
      setProfileState({ id: chosen })
      setReady(true)
      refreshMyList().catch(() => {})
    }
    if (getToken()) boot()
    else setReady(true)
    return () => { alive = false }
  }, [refreshProfiles, refreshMyList])

  const selectProfile = useCallback(async (id) => {
    setSession(null, null, id)
    setProfileState({ id })
    await refreshMyList()
  }, [refreshMyList])

  const register = useCallback(async (email, password, name) => {
    const res = await api('/auth/register', { method: 'POST', body: { email, password, name } })
    setSession(res.access_token, res.user)
    setUser(res.user)
    await refreshProfiles()
    return res
  }, [refreshProfiles])

  const login = useCallback(async (email, password) => {
    const res = await api('/auth/login', { method: 'POST', body: { email, password } })
    setSession(res.access_token, res.user)
    setUser(res.user)
    await refreshProfiles()
    return res
  }, [refreshProfiles])

  const logout = useCallback(() => {
    clearSession()
    setUser(null)
    setProfiles([])
    setProfileState(null)
    setMyListIds(new Set())
    setRatings({})
  }, [])

  const addToList = useCallback(async (titleId) => {
    await api('/api/my-list', { method: 'POST', body: { title_id: titleId } })
    setMyListIds((prev) => new Set(prev).add(titleId))
  }, [])

  const removeFromList = useCallback(async (titleId) => {
    await api(`/api/my-list/${titleId}`, { method: 'DELETE' })
    setMyListIds((prev) => { const n = new Set(prev); n.delete(titleId); return n })
  }, [])

  const setRatingValue = useCallback(async (titleId, value) => {
    await api(`/api/titles/${titleId}/rating`, { method: 'POST', body: { value } })
    setRatings((prev) => ({ ...prev, [titleId]: value }))
  }, [])

  const saveProgress = useCallback(async (titleId, seconds) => {
    try {
      await api('/api/continue-watching', { method: 'POST', body: { title_id: titleId, progress_seconds: Math.floor(seconds) } })
    } catch { /* non-fatal */ }
  }, [])

  const createProfile = useCallback(async (data) => {
    const p = await api('/api/profiles', { method: 'POST', body: data })
    const list = await refreshProfiles()
    return { profile: p, list }
  }, [refreshProfiles])

  const updateProfile = useCallback(async (id, data) => {
    const p = await api(`/api/profiles/${id}`, { method: 'PATCH', body: data })
    const list = await refreshProfiles()
    return { profile: p, list }
  }, [refreshProfiles])

  const deleteProfile = useCallback(async (id) => {
    await api(`/api/profiles/${id}`, { method: 'DELETE' })
    await refreshProfiles()
  }, [refreshProfiles])

  const value = useMemo(() => ({
    user, profiles, profile, ready,
    myListIds, ratings,
    refreshProfiles, selectProfile, register, login, logout,
    addToList, removeFromList, setRatingValue, saveProgress,
    createProfile, updateProfile, deleteProfile,
  }), [user, profiles, profile, ready, myListIds, ratings,
      refreshProfiles, selectProfile, register, login, logout,
      addToList, removeFromList, setRatingValue, saveProgress,
      createProfile, updateProfile, deleteProfile])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
