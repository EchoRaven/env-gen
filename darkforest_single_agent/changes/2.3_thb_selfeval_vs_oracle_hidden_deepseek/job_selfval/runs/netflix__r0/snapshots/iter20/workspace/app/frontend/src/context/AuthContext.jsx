import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { createApi, publicApi } from '../api.js'

const AuthContext = createContext(null)
const TOKEN_KEY = 'netflix_token'
const PROFILE_KEY = 'netflix_profile_id'

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || '')
  const [user, setUser] = useState(null)
  const [profiles, setProfiles] = useState([])
  const [activeProfileId, setActiveProfileId] = useState(() => {
    const raw = localStorage.getItem(PROFILE_KEY)
    return raw ? Number(raw) : null
  })
  const [booting, setBooting] = useState(Boolean(token))

  const activeProfile = useMemo(
    () => profiles.find((profile) => profile.id === activeProfileId) || null,
    [profiles, activeProfileId],
  )

  const applySession = useCallback((payload) => {
    localStorage.setItem(TOKEN_KEY, payload.access_token)
    setToken(payload.access_token)
    setUser(payload.user)
    setProfiles(payload.profiles || [])
  }, [])

  const refreshProfiles = useCallback(async (overrideToken = token) => {
    if (!overrideToken) return []
    const api = createApi(overrideToken, null)
    const result = await api.get('/api/profiles')
    const next = result?.items || []
    setProfiles(next)
    if (activeProfileId && !next.some((profile) => profile.id === activeProfileId)) {
      setActiveProfileId(null)
      localStorage.removeItem(PROFILE_KEY)
    }
    return next
  }, [token, activeProfileId])

  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (!token) {
        setBooting(false)
        return
      }
      try {
        const api = createApi(token, activeProfileId)
        const account = await api.get('/api/account')
        if (cancelled) return
        setUser(account.item)
        await refreshProfiles(token)
      } catch {
        if (!cancelled) {
          localStorage.removeItem(TOKEN_KEY)
          localStorage.removeItem(PROFILE_KEY)
          setToken('')
          setUser(null)
          setProfiles([])
          setActiveProfileId(null)
        }
      } finally {
        if (!cancelled) setBooting(false)
      }
    }
    restore()
    return () => { cancelled = true }
  }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(async (email, password) => {
    const payload = await publicApi.post('/auth/login', { email, password })
    applySession(payload)
    return payload
  }, [applySession])

  const register = useCallback(async ({ email, password, name }) => {
    const payload = await publicApi.post('/auth/register', { email, password, name })
    applySession(payload)
    return payload
  }, [applySession])

  const selectProfile = useCallback((profile) => {
    localStorage.setItem(PROFILE_KEY, String(profile.id))
    setActiveProfileId(profile.id)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(PROFILE_KEY)
    setToken('')
    setUser(null)
    setProfiles([])
    setActiveProfileId(null)
  }, [])

  const createProfile = useCallback(async (payload) => {
    const api = createApi(token, null)
    const result = await api.post('/api/profiles', payload)
    setProfiles((current) => [...current, result.item])
    return result.item
  }, [token])

  useEffect(() => {
    const onUnauthorized = () => logout()
    window.addEventListener('netflix:unauthorized', onUnauthorized)
    return () => window.removeEventListener('netflix:unauthorized', onUnauthorized)
  }, [logout])

  const deleteProfile = useCallback(async (profileId) => {
    const api = createApi(token, null)
    await api.delete(`/api/profiles/${profileId}`)
    setProfiles((current) => current.filter((profile) => profile.id !== profileId))
    if (activeProfileId === profileId) {
      setActiveProfileId(null)
      localStorage.removeItem(PROFILE_KEY)
    }
  }, [token, activeProfileId])

  const updateProfile = useCallback(async (profileId, payload) => {
    const api = createApi(token, null)
    const result = await api.put(`/api/profiles/${profileId}`, payload)
    setProfiles((current) => current.map((profile) => profile.id === profileId ? result.item : profile))
    return result.item
  }, [token])

  const api = useMemo(
    () => createApi(token, activeProfileId),
    [token, activeProfileId],
  )

  const value = useMemo(() => ({
    token, user, profiles, activeProfile, activeProfileId, booting, api,
    login, register, logout, selectProfile, refreshProfiles, createProfile, deleteProfile, updateProfile,
  }), [token, user, profiles, activeProfile, activeProfileId, booting, api, login, register, logout, selectProfile, refreshProfiles, createProfile, deleteProfile, updateProfile])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
