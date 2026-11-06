import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import Icon from './Icon'
import Avatar from './Avatar'
import { useApp } from '../state/AppContext'
import { api } from '../lib/api'
import { mediaUrl } from '../lib/util'
import { openTitleModal } from '../lib/modalStore'

const NAV = [
  { to: '/browse', label: 'Home' },
  { to: '/shows', label: 'Shows' },
  { to: '/movies', label: 'Movies' },
  { to: '/games', label: 'Games' },
  { to: '/new', label: 'New & Popular' },
  { to: '/mylist', label: 'My List' },
  { to: '/browse/languages', label: 'Browse by Languages' },
]

export default function Header() {
  const { user, profile, profiles, logout } = useApp()
  const nav = useNavigate()
  const [scrolled, setScrolled] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [bellOpen, setBellOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const searchRef = useRef(null)
  const inputRef = useRef(null)
  const debounceRef = useRef(null)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (!searchOpen) return
    const onDoc = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setSearchOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [searchOpen])

  useEffect(() => {
    if (searchOpen) setTimeout(() => inputRef.current?.focus(), 50)
  }, [searchOpen])

  useEffect(() => {
    if (!searchOpen) return
    clearTimeout(debounceRef.current)
    if (!query || query.trim().length < 2) { setResults([]); return }
    debounceRef.current = setTimeout(async () => {
      try {
        const rows = await api(`/api/search?q=${encodeURIComponent(query.trim())}`)
        setResults(rows.slice(0, 8))
      } catch { setResults([]) }
    }, 220)
    return () => clearTimeout(debounceRef.current)
  }, [query, searchOpen])

  const submitSearch = () => {
    const q = query.trim()
    if (!q) return
    setSearchOpen(false)
    setQuery('')
    nav(`/search?q=${encodeURIComponent(q)}`)
  }

  const closeAll = () => { setBellOpen(false); setMenuOpen(false) }

  return (
    <header className={`nf-header ${scrolled ? 'scrolled' : ''}`}>
      <Link to="/browse" className="wordmark" aria-label="Netflix home">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" />
      </Link>
      <nav className="nf-nav">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? 'active' : '')}>
            {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="nf-header-right">
        <div className={`search-wrap ${searchOpen ? 'open' : ''}`} ref={searchRef}>
          <button
            className="icon-btn"
            aria-label="Search titles"
            onClick={() => { setMenuOpen(false); setBellOpen(false); setSearchOpen((v) => !v) }}
          >
            <Icon name="search" />
          </button>
          <input
            ref={inputRef}
            className="search-input"
            placeholder="Titles, genres"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submitSearch(); if (e.key === 'Escape') setSearchOpen(false) }}
          />
          {searchOpen && results !== null && (
            <div className="search-results">
              {results.length === 0 && (
                <div className="dropdown-empty">
                  {query.trim().length < 2 ? 'Type at least 2 characters to search.' : 'No titles found. Try another search.'}
                </div>
              )}
              {results.map((t) => (
                <div key={t.id} className="search-result-row" onClick={() => { setSearchOpen(false); setQuery(''); openTitleModal(t.id) }}>
                  <img src={mediaUrl(t.backdrop || t.poster)} alt="" />
                  <div>
                    <div className="sr-name">{t.name}</div>
                    <div className="sr-sub">{t.year} · {t.kind === 'series' ? 'Series' : 'Film'}{t.genre ? ` · ${t.genre}` : ''}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ position: 'relative' }}>
          <button className="icon-btn" aria-label="Notifications" onClick={() => { setMenuOpen(false); setBellOpen((v) => !v) }}>
            <Icon name="bell_base" />
          </button>
          {bellOpen && (
            <div className="dropdown right" onMouseLeave={() => setBellOpen(false)}>
              <div className="dropdown-section">Notifications</div>
              <div className="dropdown-empty">You’re all caught up — no new notifications.</div>
            </div>
          )}
        </div>
        <div className="profile-menu">
          {profile && <Avatar profile={profileById(profiles, profile.id)} size={34} className="profile-avatar" />}
          <button className="icon-btn" aria-label="Profile menu" onClick={() => { setBellOpen(false); setMenuOpen((v) => !v) }}>
            <Icon name="chevron_down" size={16} className={`caret ${menuOpen ? 'open' : ''}`} />
          </button>
          {menuOpen && (
            <div className="dropdown right" onMouseLeave={() => setMenuOpen(false)}>
              <div className="dropdown-section">Profile: {profileById(profiles, profile.id)?.name}</div>
              <button className="dropdown-item" onClick={() => { closeAll(); nav('/profiles') }}>Manage Profiles</button>
              <button className="dropdown-item" onClick={() => { closeAll(); nav('/account') }}>Account</button>
              <div className="dropdown-divider" />
              <button className="dropdown-item" onClick={() => { logout(); nav('/') }}>Sign out of Netflix</button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

function profileById(list, id) {
  return list.find((p) => String(p.id) === String(id)) || { name: '?', avatar: 'avatar_0' }
}
