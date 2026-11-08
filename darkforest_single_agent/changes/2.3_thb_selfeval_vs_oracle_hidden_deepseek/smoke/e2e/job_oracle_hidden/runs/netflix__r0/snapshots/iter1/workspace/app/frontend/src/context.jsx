import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  api, clearSession, getStoredProfileId, getStoredUser, getToken, storeProfile, storeSession,
} from './api'

const AppContext = createContext(null)

export function AppProvider({ children }) {
  const [token, setToken] = useState(() => getToken())
  const [user, setUser] = useState(() => getStoredUser())
  const [profiles, setProfiles] = useState([])
  const [profileId, setProfileId] = useState(() => getStoredProfileId())
  const [booting, setBooting] = useState(Boolean(getToken()))

  const profile = useMemo(
    () => profiles.find(item => Number(item.id) === Number(profileId)) || null,
    [profiles, profileId],
  )

  const refreshProfiles = useCallback(async (preferredId) => {
    if (!getToken()) {
      setProfiles([])
      return []
    }
    const list = await api('/api/profiles')
    setProfiles(list)
    const wanted = preferredId ?? getStoredProfileId()
    const selected = list.find(item => Number(item.id) === Number(wanted)) || list[0]
    if (selected) {
      setProfileId(Number(selected.id))
      storeProfile(selected.id)
    } else {
      setProfileId(null)
      storeProfile(null)
    }
    return list
  }, [])

  useEffect(() => {
    let cancelled = false
    if (!getToken()) {
      setBooting(false)
      return
    }
    refreshProfiles()
      .catch(() => {})
      .finally(() => { if (!cancelled) setBooting(false) })
    return () => { cancelled = true }
  }, [refreshProfiles])

  useEffect(() => {
    const onUnauthorized = () => {
      clearSession()
      setToken(null)
      setUser(null)
      setProfiles([])
      setProfileId(null)
    }
    window.addEventListener('netflix:unauthorized', onUnauthorized)
    return () => window.removeEventListener('netflix:unauthorized', onUnauthorized)
  }, [])

  const finishAuth = useCallback(async (session) => {
    storeSession(session)
    setToken(session.access_token)
    setUser(session.user)
    let list = []
    try {
      list = await refreshProfiles()
    } catch {
      list = []
    }
    return list
  }, [refreshProfiles])

  const login = useCallback(async (email, password) => {
    const session = await api('/auth/login', { method: 'POST', body: { email, password } })
    const list = await finishAuth(session)
    return { session, profiles: list }
  }, [finishAuth])

  const register = useCallback(async ({ email, password, name }) => {
    const session = await api('/auth/register', { method: 'POST', body: { email, password, name } })
    const list = await finishAuth(session)
    return { session, profiles: list }
  }, [finishAuth])

  const selectProfile = useCallback((nextProfile) => {
    if (!nextProfile) return
    setProfileId(Number(nextProfile.id))
    storeProfile(nextProfile.id)
  }, [])

  const logout = useCallback(() => {
    clearSession()
    setToken(null)
    setUser(null)
    setProfiles([])
    setProfileId(null)
  }, [])

  const value = useMemo(() => ({
    token, user, profiles, profile, profileId, booting,
    login, register, logout, selectProfile, refreshProfiles, setProfiles,
  }), [token, user, profiles, profile, profileId, booting, login, register, logout, selectProfile, refreshProfiles])

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const context = useContext(AppContext)
  if (!context) throw new Error('useApp must be used within AppProvider')
  return context
}
