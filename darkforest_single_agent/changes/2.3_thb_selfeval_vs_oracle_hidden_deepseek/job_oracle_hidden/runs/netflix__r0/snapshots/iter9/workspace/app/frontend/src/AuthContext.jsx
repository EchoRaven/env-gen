import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { ApiError, request } from './api'

const AuthContext = createContext(null)
const TOKEN_KEY = 'netflix_access_token'
const USER_KEY = 'netflix_user'
const PROFILE_KEY = 'netflix_profile_id'

function readJson(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || 'null')
  } catch {
    return null
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(() => readJson(USER_KEY))
  const [profiles, setProfiles] = useState([])
  const [profileId, setProfileId] = useState(() => Number(localStorage.getItem(PROFILE_KEY)) || null)
  const [loading, setLoading] = useState(Boolean(localStorage.getItem(TOKEN_KEY)))

  const clearSession = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem(PROFILE_KEY)
    setToken(null)
    setUser(null)
    setProfiles([])
    setProfileId(null)
  }, [])

  const authFetch = useCallback(
    async (path, options = {}) => {
      try {
        return await request(path, options, token, profileId)
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) clearSession()
        throw error
      }
    },
    [token, profileId, clearSession],
  )

  const refreshProfiles = useCallback(
    async (activeToken = token) => {
      if (!activeToken) return []
      const result = await request('/api/profiles', {}, activeToken, profileId)
      setProfiles(result)
      const valid = result.some((profile) => profile.id === profileId)
      if (!valid) {
        const next = result[0]?.id || null
        setProfileId(next)
        if (next) localStorage.setItem(PROFILE_KEY, String(next))
        else localStorage.removeItem(PROFILE_KEY)
      }
      return result
    },
    [token, profileId],
  )

  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (!token) {
        setLoading(false)
        return
      }
      try {
        const result = await request('/api/profiles', {}, token, profileId)
        if (cancelled) return
        setProfiles(result)
        const saved = result.find((profile) => profile.id === profileId) || result[0]
        if (saved) {
          setProfileId(saved.id)
          localStorage.setItem(PROFILE_KEY, String(saved.id))
        }
      } catch (error) {
        if (!cancelled && error.status === 401) clearSession()
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    restore()
    return () => {
      cancelled = true
    }
    // The token is the only trigger needed for session restoration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const acceptSession = useCallback((result) => {
    localStorage.setItem(TOKEN_KEY, result.access_token)
    localStorage.setItem(USER_KEY, JSON.stringify(result.user))
    setToken(result.access_token)
    setUser(result.user)
    const nextProfiles = result.profiles || (result.profile ? [result.profile] : [])
    setProfiles(nextProfiles)
    const first = nextProfiles[0]
    if (first) {
      setProfileId(first.id)
      localStorage.setItem(PROFILE_KEY, String(first.id))
    } else {
      setProfileId(null)
      localStorage.removeItem(PROFILE_KEY)
    }
    return result
  }, [])

  const login = useCallback(
    async (email, password) => {
      const result = await request('/auth/login', {
        method: 'POST',
        body: { email, password },
      })
      return acceptSession(result)
    },
    [acceptSession],
  )

  const register = useCallback(
    async (email, password, name) => {
      const result = await request('/auth/register', {
        method: 'POST',
        body: { email, password, name },
      })
      return acceptSession(result)
    },
    [acceptSession],
  )

  const selectProfile = useCallback((profile) => {
    setProfileId(profile.id)
    localStorage.setItem(PROFILE_KEY, String(profile.id))
  }, [])

  const createProfile = useCallback(
    async (payload) => {
      const result = await request('/api/profiles', { method: 'POST', body: payload }, token, profileId)
      setProfiles((current) => [...current, result])
      return result
    },
    [token, profileId],
  )

  const updateProfile = useCallback(
    async (id, payload) => {
      const result = await request(`/api/profiles/${id}`, { method: 'PUT', body: payload }, token, profileId)
      setProfiles((current) => current.map((profile) => (profile.id === id ? result : profile)))
      return result
    },
    [token, profileId],
  )

  const deleteProfile = useCallback(
    async (id) => {
      await request(`/api/profiles/${id}`, { method: 'DELETE' }, token, profileId)
      setProfiles((current) => current.filter((profile) => profile.id !== id))
      if (profileId === id) {
        setProfileId(null)
        localStorage.removeItem(PROFILE_KEY)
      }
    },
    [token, profileId],
  )

  const activeProfile = useMemo(
    () => profiles.find((profile) => profile.id === profileId) || null,
    [profiles, profileId],
  )

  const value = useMemo(
    () => ({
      token,
      user,
      profiles,
      profileId,
      activeProfile,
      loading,
      login,
      register,
      logout: clearSession,
      refreshProfiles,
      createProfile,
      updateProfile,
      deleteProfile,
      selectProfile,
      authFetch,
    }),
    [
      token,
      user,
      profiles,
      profileId,
      activeProfile,
      loading,
      login,
      register,
      clearSession,
      refreshProfiles,
      createProfile,
      updateProfile,
      deleteProfile,
      selectProfile,
      authFetch,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}

