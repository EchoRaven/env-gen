import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import Avatar from './Avatar'
import Icon from './Icon'
import Logo from './Logo'

const NAV = [
  { label: 'Home', to: '/browse' },
  { label: 'Shows', to: '/shows' },
  { label: 'Movies', to: '/movies' },
  { label: 'Games', to: '/games' },
  { label: 'New & Popular', to: '/new' },
  { label: 'My List', to: '/my-list' },
  { label: 'Browse by Languages', to: '/browse/languages' },
]

export default function Header() {
  const [scrolled, setScrolled] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const searchRef = useRef(null)
  const menuRef = useRef(null)
  const navigate = useNavigate()
  const location = useLocation()
  const { profile, logout } = useAuth()

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    setSearchOpen(false)
    setMenuOpen(false)
    setQuery('')
    setResults([])
  }, [location.pathname])

  useEffect(() => {
    if (!searchOpen) return
    searchRef.current?.focus()
    const onKey = (event) => {
      if (event.key === 'Escape') {
        setSearchOpen(false)
        setResults([])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [searchOpen])

  useEffect(() => {
    const onDown = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) setMenuOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [])

  useEffect(() => {
    const term = query.trim()
    if (!searchOpen || term.length < 2) {
      setResults([])
      setSearching(false)
      return undefined
    }
    let active = true
    setSearching(true)
    const timer = setTimeout(async () => {
      try {
        const data = await api.get(`/api/search?q=${encodeURIComponent(term)}`)
        if (active) setResults((data.items || []).slice(0, 7))
      } catch {
        if (active) setResults([])
      } finally {
        if (active) setSearching(false)
      }
    }, 260)
    return () => { active = false; clearTimeout(timer) }
  }, [query, searchOpen])

  const submitSearch = (event) => {
    event.preventDefault()
    const term = query.trim()
    if (!term) return
    setSearchOpen(false)
    navigate(`/search?q=${encodeURIComponent(term)}`)
  }

  const openResult = (id) => {
    setSearchOpen(false)
    setResults([])
    navigate(`/title/${id}`)
  }

  const signOut = () => {
    setMenuOpen(false)
    logout()
    navigate('/')
  }

  return (
    <header className={`site-header ${scrolled ? 'scrolled' : ''}`}>
      <div className="header-left">
        <Logo width={92} />
        <nav className="primary-nav" aria-label="Primary">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/browse'}
              className={({ isActive }) => isActive ? 'active' : ''}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="header-right" ref={menuRef}>
        <div className={`search-shell ${searchOpen ? 'open' : ''}`}>
          <form onSubmit={submitSearch} className="search-form">
            <button
              type={searchOpen ? 'submit' : 'button'}
              className="icon-btn header-icon"
              aria-label={searchOpen ? 'Submit search' : 'Open search'}
              onClick={() => { if (!searchOpen) setSearchOpen(true) }}
            >
              <Icon name="search" size={22} />
            </button>
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Titles, genres, people"
              aria-label="Search titles"
              tabIndex={searchOpen ? 0 : -1}
            />
            {searchOpen ? (
              <button type="button" className="icon-btn search-close" aria-label="Close search" onClick={() => { setSearchOpen(false); setResults([]) }}>
                <Icon name="close" size={20} />
              </button>
            ) : null}
          </form>
          {searchOpen && query.trim().length >= 2 ? (
            <div className="search-results">
              {searching ? <div className="search-note">Searching…</div> : null}
              {!searching && results.length === 0 ? <div className="search-note">No titles match “{query.trim()}”.</div> : null}
              {results.map((title) => (
                <button key={title.id} className="search-result" onClick={() => openResult(title.id)}>
                  <img src={title.poster} alt="" />
                  <span>
                    <strong>{title.name}</strong>
                    <small>{title.year} · {title.kind === 'series' ? 'Series' : 'Film'}</small>
                  </span>
                  <Icon name="play" size={18} />
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <Link to="/notifications" className="icon-btn header-icon" aria-label="Notifications">
          <Icon name="bell" size={22} />
        </Link>

        <div className="profile-menu-wrap">
          <button
            className="profile-trigger"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span className="header-profile-name">{profile?.name}</span>
            <Avatar profile={profile} size={34} />
            <Icon name="chevronDown" size={13} className={menuOpen ? 'caret up' : 'caret'} />
          </button>
          {menuOpen ? (
            <div className="profile-menu" role="menu">
              <div className="profile-menu-head">
                <Avatar profile={profile} size={38} />
                <div>
                  <strong>{profile?.name || 'Profile'}</strong>
                  <span>Watching now</span>
                </div>
              </div>
              <Link role="menuitem" to="/profiles" onClick={() => setMenuOpen(false)}>Manage Profiles</Link>
              <Link role="menuitem" to="/account" onClick={() => setMenuOpen(false)}>Account</Link>
              <button role="menuitem" onClick={signOut}>Sign out of Netflix</button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  )
}
