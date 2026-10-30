import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, setStaleProfileHandler, setUnauthorizedHandler, store } from './api.js'

const SessionCtx = createContext(null)

export function SessionProvider({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [token, setToken] = useState(store.token)
  const [user, setUser] = useState(null)
  const [profiles, setProfiles] = useState([])
  const [profileId, setProfileId] = useState(store.profileId)
  // Per-profile overrides so every card/modal reflects My List + rating changes immediately.
  const [listState, setListState] = useState({})
  const [ratingState, setRatingState] = useState({})
  const [listVersion, setListVersion] = useState(0)
  const [toast, setToast] = useState(null)

  const logout = useCallback(() => {
    store.token = null
    store.profileId = null
    setToken(null); setUser(null); setProfiles([]); setProfileId(null)
    setListState({}); setRatingState({})
    navigate('/login')
  }, [navigate])

  useEffect(() => { setUnauthorizedHandler(logout) }, [logout])
  useEffect(() => {
    setStaleProfileHandler(() => { setProfileId(null); setListState({}); setRatingState({}) })
  }, [])

  const refreshProfiles = useCallback(async () => {
    const res = await api.profiles()
    setProfiles(res.items)
    return res.items
  }, [])

  useEffect(() => {
    if (!token) return
    api.me().then((r) => setUser(r.item)).catch(() => {})
    refreshProfiles().catch(() => {})
  }, [token, refreshProfiles])

  const signIn = useCallback((data) => {
    store.token = data.access_token
    store.profileId = null
    setProfileId(null)
    setToken(data.access_token)
    setUser(data.user || null)
  }, [])

  const selectProfile = useCallback((p) => {
    store.profileId = p ? p.id : null
    setProfileId(p ? String(p.id) : null)
    setListState({}); setRatingState({})
  }, [])

  const profile = useMemo(
    () => profiles.find((p) => String(p.id) === String(profileId)) || null,
    [profiles, profileId]
  )

  const flash = useCallback((msg) => {
    setToast(msg)
    clearTimeout(flash._t)
    flash._t = setTimeout(() => setToast(null), 2600)
  }, [])

  const inList = useCallback((title) => (
    title && listState[title.id] !== undefined ? listState[title.id] : !!(title && title.in_my_list)
  ), [listState])

  const toggleList = useCallback(async (title) => {
    const was = inList(title)
    setListState((s) => ({ ...s, [title.id]: !was }))
    try {
      if (was) await api.removeFromList(title.id)
      else await api.addToList(title.id)
      setListVersion((v) => v + 1)
      flash(was ? `Removed "${title.name}" from My List` : `Added "${title.name}" to My List`)
    } catch (e) {
      setListState((s) => ({ ...s, [title.id]: was }))
      flash(e.message)
    }
  }, [inList, flash])

  const ratingOf = useCallback((title) => (
    title && ratingState[title.id] !== undefined ? ratingState[title.id] : (title ? title.my_rating ?? null : null)
  ), [ratingState])

  const rateTitle = useCallback(async (title, value) => {
    const prev = ratingOf(title)
    const next = prev === value ? 0 : value
    setRatingState((s) => ({ ...s, [title.id]: next || null }))
    try {
      await api.rate(title.id, next)
    } catch (e) {
      setRatingState((s) => ({ ...s, [title.id]: prev }))
      flash(e.message)
    }
  }, [ratingOf, flash])

  const openTitle = useCallback((id) => {
    const p = new URLSearchParams(location.search)
    p.set('title', id)
    navigate({ pathname: location.pathname, search: '?' + p.toString() })
  }, [location, navigate])

  const closeTitle = useCallback(() => {
    const p = new URLSearchParams(location.search)
    p.delete('title')
    const s = p.toString()
    navigate({ pathname: location.pathname, search: s ? '?' + s : '' })
  }, [location, navigate])

  const value = {
    token, user, profiles, profile, profileId, signIn, logout, selectProfile, refreshProfiles,
    inList, toggleList, ratingOf, rateTitle, listVersion, openTitle, closeTitle, flash, toast,
  }
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>
}

export const useSession = () => useContext(SessionCtx)

// Small data hook: runs `fn` when deps change, exposes {data, error, loading}.
export function useAsync(fn, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true }))
    fn().then(
      (data) => alive && setState({ data, error: null, loading: false }),
      (error) => alive && setState({ data: null, error, loading: false })
    )
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}
