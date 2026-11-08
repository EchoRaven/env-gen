import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('nf_token') || '')
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('nf_user') || 'null') } catch { return null }
  })
  const [profiles, setProfiles] = useState([])
  const [profile, setProfileState] = useState(() => {
    try { return JSON.parse(localStorage.getItem('nf_profile') || 'null') } catch { return null }
  })
  const [loading, setLoading] = useState(Boolean(token))

  const setProfile = useCallback((next) => {
    setProfileState(next)
    if (next) localStorage.setItem('nf_profile', JSON.stringify(next))
    else localStorage.removeItem('nf_profile')
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('nf_token')
    localStorage.removeItem('nf_user')
    localStorage.removeItem('nf_profile')
    setToken('')
    setUser(null)
    setProfiles([])
    setProfileState(null)
  }, [])

  const refreshProfiles = useCallback(async () => {
    if (!token) return []
    try {
      const data = await api.get('/api/profiles')
      const list = data.items || []
      setProfiles(list)
      setProfileState((current) => {
        const valid = current && list.find((p) => p.id === current.id)
        const next = valid || list[0] || null
        if (next) localStorage.setItem('nf_profile', JSON.stringify(next))
        return next
      })
      return list
    } catch (err) {
      if (err.status === 401) logout()
      return []
    }
  }, [token, logout])

  useEffect(() => {
    let mounted = true
    const boot = async () => {
      if (!token) { setLoading(false); return }
      try {
        const data = await api.get('/api/me')
        if (!mounted) return
        setUser(data.item)
        setProfiles(data.item.profiles || [])
        const stored = profile
        const valid = stored && (data.item.profiles || []).find((p) => p.id === stored.id)
        const next = valid || (data.item.profiles || [])[0] || null
        setProfileState(next)
        if (next) localStorage.setItem('nf_profile', JSON.stringify(next))
      } catch (err) {
        if (mounted && err.status === 401) logout()
      } finally {
        if (mounted) setLoading(false)
      }
    }
    boot()
    return () => { mounted = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const signIn = useCallback((data) => {
    if (data.access_token) {
      localStorage.setItem('nf_token', data.access_token)
      setToken(data.access_token)
    }
    if (data.user) {
      localStorage.setItem('nf_user', JSON.stringify(data.user))
      setUser(data.user)
    }
    if (data.profiles) {
      setProfiles(data.profiles)
      if (data.profiles.length) {
        setProfile(data.profiles[0])
      }
    }
  }, [setProfile])

  const value = useMemo(() => ({
    token, user, profiles, profile, loading,
    setUser, setProfiles, setProfile, refreshProfiles, signIn, logout,
    isAuthenticated: Boolean(token),
  }), [token, user, profiles, profile, loading, setProfile, refreshProfiles, signIn, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
