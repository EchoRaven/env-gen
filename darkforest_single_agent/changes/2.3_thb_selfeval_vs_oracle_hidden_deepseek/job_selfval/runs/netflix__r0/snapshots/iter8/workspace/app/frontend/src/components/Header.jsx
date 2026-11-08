import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import Icon, { BrandLogo } from './Icon.jsx'

const NAV_ITEMS = [
  { label: 'Home', to: '/browse' },
  { label: 'Shows', to: '/shows' },
  { label: 'Movies', to: '/movies' },
  { label: 'Games', to: '/games' },
  { label: 'New & Popular', to: '/new' },
  { label: 'My List', to: '/my-list' },
  { label: 'Browse by Languages', to: '/browse/languages' },
]

function isActive(pathname, to) {
  if (to === '/browse') return pathname === '/browse' || pathname.startsWith('/title/')
  return pathname === to || pathname.startsWith(`${to}/`)
}

export default function Header() {
  const { api, activeProfile, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [scrolled, setScrolled] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [notificationCount, setNotificationCount] = useState(0)
  const [notificationError, setNotificationError] = useState('')
  const [languageOpen, setLanguageOpen] = useState(false)
  const searchRef = useRef(null)
  const accountRef = useRef(null)
  const notificationsRef = useRef(null)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    setMenuOpen(false)
    setNotificationsOpen(false)
    setLanguageOpen(false)
    setMobileNavOpen(false)
  }, [location.pathname, location.search])

  useEffect(() => {
    let cancelled = false
    api.get('/api/titles?sort=new&limit=6').then((result) => {
      if (cancelled) return
      setNotifications(result.items || [])
      setNotificationCount((result.items || []).length)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [api])

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus()
  }, [searchOpen])

  useEffect(() => {
    function close(event) {
      if (accountRef.current && !accountRef.current.contains(event.target)) setMenuOpen(false)
      if (notificationsRef.current && !notificationsRef.current.contains(event.target)) setNotificationsOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  async function toggleNotifications() {
    const next = !notificationsOpen
    setNotificationsOpen(next)
    if (next) {
      setNotificationError('')
      try {
        const result = await api.get('/api/titles?sort=new&limit=6')
        setNotifications(result.items || [])
        setNotificationCount((result.items || []).length)
      } catch (error) {
        setNotificationError(error.message)
      }
    }
  }

  function submitSearch(event) {
    event.preventDefault()
    const q = query.trim()
    if (!q) return
    setSearchOpen(false)
    navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  function openTitle(id) {
    setNotificationsOpen(false)
    setMenuOpen(false)
    const base = location.pathname.startsWith('/browse') ? location.pathname : '/browse'
    navigate(`${base}?title=${id}`)
  }

  return (
    <header className={`site-header ${scrolled ? 'scrolled' : ''}`}>
      <div className="header-left">
        <Link to="/browse" className="logo-link" aria-label="Netflix home"><BrandLogo /></Link>
        <div className="mobile-nav-wrap">
          <button type="button" className="mobile-nav-toggle" onClick={() => setMobileNavOpen((open) => !open)} aria-expanded={mobileNavOpen} aria-label="Browse navigation">
            Browse <Icon name="chevron-down" size={13} />
          </button>
          {mobileNavOpen && (
            <nav className="mobile-nav-menu" aria-label="Mobile navigation">
              {NAV_ITEMS.map((item) => (
                <Link key={item.to} to={item.to} className={isActive(location.pathname, item.to) ? 'active' : ''} onClick={() => setMobileNavOpen(false)}>{item.label}</Link>
              ))}
            </nav>
          )}
        </div>
        <nav className="primary-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => item.label === 'Browse by Languages' ? (
            <div className="nav-language" key={item.to}>
              <button
                type="button"
                className={`nav-link nav-button ${isActive(location.pathname, item.to) ? 'active' : ''}`}
                onClick={() => setLanguageOpen((open) => !open)}
              >
                {item.label}<Icon name="chevron-down" size={12} />
              </button>
              {languageOpen && (
                <div className="dropdown nav-dropdown">
                  <button type="button" onClick={() => { setLanguageOpen(false); navigate('/browse/languages') }}>Original Language</button>
                  {['English', 'Japanese', 'Korean', 'Spanish', 'Hindi'].map((language) => (
                    <button type="button" key={language} onClick={() => { setLanguageOpen(false); navigate(`/browse/languages?language=${language}`) }}>{language}</button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <Link key={item.to} to={item.to} className={`nav-link ${isActive(location.pathname, item.to) ? 'active' : ''}`}>
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="header-right">
        <form className={`header-search ${searchOpen ? 'open' : ''}`} onSubmit={submitSearch}>
          <button type="button" className="icon-button" aria-label="Search" onClick={() => setSearchOpen((open) => !open)}>
            <Icon name="search" size={22} />
          </button>
          {searchOpen && (
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Titles and genres"
              aria-label="Search titles"
              onBlur={() => { if (!query.trim()) setSearchOpen(false) }}
            />
          )}
        </form>
        <div className="notification-wrap" ref={notificationsRef}>
          <button type="button" className="icon-button bell-button" aria-label="Notifications" onClick={toggleNotifications}>
            <Icon name="bell" size={22} />
            {notificationCount > 0 && <span className="notification-badge">{notificationCount}</span>}
          </button>
          {notificationsOpen && (
            <div className="dropdown notification-menu">
              <div className="dropdown-heading">New arrivals</div>
              {notificationError && <div className="empty-inline">{notificationError}</div>}
              {!notificationError && notifications.length === 0 && <div className="empty-inline">No new notifications.</div>}
              {notifications.map((title) => (
                <button key={title.id} type="button" className="notification-item" onClick={() => openTitle(title.id)}>
                  <img src={title.backdrop || title.poster} alt="" />
                  <span>
                    <strong>{title.name}</strong>
                    <small>{title.kind === 'series' ? 'New season' : 'New release'} · {title.year}</small>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="account-wrap" ref={accountRef}>
          <button type="button" className="account-button" onClick={() => setMenuOpen((open) => !open)} aria-label="Account menu" aria-expanded={menuOpen}>
            {activeProfile?.is_kids && <span className="header-kid-label">Kids</span>}
            <img src={activeProfile?.avatar || '/assets/avatars/avatar_1.svg'} alt="" />
            <Icon name="chevron-down" size={13} />
          </button>
          {menuOpen && (
            <div className="dropdown account-menu">
              {activeProfile && <div className="account-current"><img src={activeProfile.avatar} alt="" /><span>{activeProfile.name}</span></div>}
              <button type="button" onClick={() => navigate('/profiles')}>Manage Profiles</button>
              <button type="button" onClick={() => navigate('/help#transfer')}>Transfer Profile</button>
              <button type="button" onClick={() => navigate('/account')}>Account</button>
              <button type="button" onClick={() => navigate('/help')}>Help Center</button>
              <button type="button" onClick={() => { logout(); navigate('/') }}>Sign out of Netflix</button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
