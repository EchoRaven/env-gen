import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { AssetIcon, Wordmark } from '../icons'
import { LANGUAGES } from '../utils'
import { ProfileAvatar } from './ProfileAvatar'

const NAV_ITEMS = [
  { to: '/browse', label: 'Home', end: true },
  { to: '/shows', label: 'Shows', menu: 'genres' },
  { to: '/movies', label: 'Movies', menu: 'genres' },
  { to: '/games', label: 'Games' },
  { to: '/new', label: 'New & Popular' },
  { to: '/my-list', label: 'My List' },
  { to: '/browse/languages', label: 'Browse by Languages', menu: 'languages' },
]

function NavItem({ item, genres, onNavigate, onSelect }) {
  const [open, setOpen] = useState(false)
  const timeout = useRef(null)
  const show = () => {
    clearTimeout(timeout.current)
    setOpen(true)
  }
  const hide = () => {
    timeout.current = setTimeout(() => setOpen(false), 140)
  }
  const hasMenu = Boolean(item.menu)
  return (
    <div className={`nav-item ${open ? 'is-open' : ''}`} onMouseEnter={show} onMouseLeave={hide}>
      <NavLink
        to={item.to}
        end={item.end}
        className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
        onClick={() => { setOpen(false); onSelect?.() }}
        aria-haspopup={hasMenu || undefined}
        aria-expanded={hasMenu ? open : undefined}
      >
        {item.label}
        {hasMenu ? <span className="nav-caret" aria-hidden="true" /> : null}
      </NavLink>
      {hasMenu && open ? (
        <div className="nav-dropdown" onMouseEnter={show} onMouseLeave={hide}>
          <div className="nav-dropdown-heading">
            {item.menu === 'genres' ? 'Browse Genres' : 'Browse by Language'}
          </div>
          {item.menu === 'genres'
            ? genres.map((genre) => (
                <button
                  key={genre.id}
                  className="nav-dropdown-item"
                  onClick={() => {
                    setOpen(false)
                    onNavigate(`/browse/genre/${genre.id}`)
                  }}
                >
                  <span>{genre.name}</span>
                  <span className="nav-count">{genre.title_count}</span>
                </button>
              ))
            : LANGUAGES.map((language) => (
                <button
                  key={language.code}
                  className="nav-dropdown-item"
                  onClick={() => {
                    setOpen(false)
                    onNavigate(`/browse/languages?language=${language.code}`)
                  }}
                >
                  {language.name}
                </button>
              ))}
        </div>
      ) : null}
    </div>
  )
}

export function Header({ searchPage = false }) {
  const { user, activeProfile, logout, authFetch } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [genres, setGenres] = useState([])
  const [searchOpen, setSearchOpen] = useState(searchPage)
  const [query, setQuery] = useState(new URLSearchParams(location.search).get('q') || '')
  const [accountOpen, setAccountOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [accountModal, setAccountModal] = useState(false)
  const [helpModal, setHelpModal] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const searchRef = useRef(null)
  const accountRef = useRef(null)

  useEffect(() => {
    authFetch('/api/genres').then(setGenres).catch(() => setGenres([]))
  }, [authFetch])

  useEffect(() => {
    setQuery(new URLSearchParams(location.search).get('q') || '')
    setSearchOpen(searchPage)
  }, [location.search, searchPage])

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus()
  }, [searchOpen])

  useEffect(() => {
    const onPointerDown = (event) => {
      if (accountRef.current && !accountRef.current.contains(event.target)) setAccountOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [])

  const submitSearch = (event) => {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) return
    setSearchOpen(false)
    navigate(`/search?q=${encodeURIComponent(trimmed)}`)
  }

  const openNotifications = async () => {
    const next = !notificationsOpen
    setNotificationsOpen(next)
    setAccountOpen(false)
    if (next && notifications.length === 0) {
      try {
        const titles = await authFetch('/api/titles/trending?limit=4')
        setNotifications(titles)
      } catch {
        setNotifications([])
      }
    }
  }

  const onLogout = () => {
    setAccountOpen(false)
    logout()
    navigate('/')
  }

  return (
    <>
      <header className={`top-header ${scrolled ? 'scrolled' : ''} ${searchOpen ? 'searching' : ''}`}>
        <div className="header-left">
          <Link to="/browse" className="brand-link" aria-label="Netflix home">
            <Wordmark height={26} />
          </Link>
          <button
            className="mobile-menu-button"
            aria-label="Toggle navigation menu"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((value) => !value)}
          >
            <span /><span /><span />
          </button>
          <nav className={`primary-nav ${mobileOpen ? 'mobile-open' : ''}`} aria-label="Main navigation">
            {NAV_ITEMS.map((item) => (
              <NavItem key={item.label} item={item} genres={genres} onNavigate={navigate} onSelect={() => setMobileOpen(false)} />
            ))}
          </nav>
        </div>
        <div className="header-right">
          <form className={`header-search ${searchOpen ? 'open' : ''}`} onSubmit={submitSearch}>
            <button
              type="button"
              className="icon-button"
              aria-label={searchOpen ? 'Close search' : 'Search titles'}
              onClick={() => setSearchOpen((value) => !value)}
            >
              <AssetIcon name={searchOpen ? 'close' : 'search'} size={22} />
            </button>
            <input
              ref={searchRef}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Titles, people, genres"
              aria-label="Search titles, people, genres"
              tabIndex={searchOpen ? 0 : -1}
            />
          </form>
          <button className="notification-button icon-button" aria-label="Notifications" onClick={openNotifications}>
            <AssetIcon name="bell" size={22} />
            <span className="notification-dot" />
          </button>
          <div className="account-control" ref={accountRef}>
            <button
              className="profile-menu-button"
              onClick={() => {
                setAccountOpen((value) => !value)
                setNotificationsOpen(false)
              }}
              aria-haspopup="menu"
              aria-expanded={accountOpen}
              aria-label="Account menu"
            >
              <ProfileAvatar profile={activeProfile} size={32} />
              <span className="account-caret" />
            </button>
            {accountOpen ? (
              <div className="account-dropdown" role="menu">
                {activeProfile ? (
                  <div className="account-profile-line">
                    <ProfileAvatar profile={activeProfile} size={36} />
                    <span>{activeProfile.name}</span>
                  </div>
                ) : null}
                <button role="menuitem" onClick={() => navigate('/profiles?manage=1')}>
                  Manage Profiles
                </button>
                <button role="menuitem" onClick={() => navigate('/profiles?manage=1')}>
                  Transfer Profile
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setAccountModal(true)
                    setAccountOpen(false)
                  }}
                >
                  Account
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setHelpModal(true)
                    setAccountOpen(false)
                  }}
                >
                  Help Center
                </button>
                <button role="menuitem" className="sign-out-item" onClick={onLogout}>
                  Sign out of Netflix
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      {notificationsOpen ? (
        <div className="notification-panel">
          <div className="notification-panel-head">
            <h3>New & Popular</h3>
            <button className="icon-button" onClick={() => setNotificationsOpen(false)} aria-label="Close notifications">
              <AssetIcon name="close" size={18} />
            </button>
          </div>
          {notifications.length ? (
            notifications.map((title) => (
              <button
                key={title.id}
                className="notification-item"
                onClick={() => {
                  setNotificationsOpen(false)
                  navigate(`/title/${title.id}`, { state: { from: location.pathname } })
                }}
              >
                <img src={title.backdrop} alt="" />
                <span>
                  <strong>{title.name}</strong>
                  <small>Trending now · {title.year}</small>
                </span>
              </button>
            ))
          ) : (
            <p className="notification-empty">No new notifications.</p>
          )}
        </div>
      ) : null}

      {accountModal ? (
        <div className="modal-backdrop account-modal-backdrop" onClick={() => setAccountModal(false)}>
          <div className="account-modal" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" onClick={() => setAccountModal(false)} aria-label="Close account details">
              <AssetIcon name="close" size={24} />
            </button>
            <h2>Account</h2>
            <div className="account-detail-row">
              <span>Name</span>
              <strong>{user?.name || '—'}</strong>
            </div>
            <div className="account-detail-row">
              <span>Email</span>
              <strong>{user?.email || '—'}</strong>
            </div>
            <div className="account-detail-row">
              <span>Profiles</span>
              <strong>{activeProfile ? activeProfile.name : 'None selected'}</strong>
            </div>
            <button
              className="button button-white account-manage-button"
              onClick={() => {
                setAccountModal(false)
                navigate('/profiles')
              }}
            >
              Manage profiles
            </button>
          </div>
        </div>
      ) : null}

      {helpModal ? (
        <div className="modal-backdrop account-modal-backdrop" onClick={() => setHelpModal(false)}>
          <div className="account-modal" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" onClick={() => setHelpModal(false)} aria-label="Close help center">
              <AssetIcon name="close" size={24} />
            </button>
            <h2>Help Center</h2>
            <p className="help-copy">Browse the catalog, select a profile, and use the controls on each title to play, add to My List, or rate it.</p>
            <p className="help-copy">My List, ratings, and Continue Watching are saved separately for each profile.</p>
            <button
              className="button button-white account-manage-button"
              onClick={() => { setHelpModal(false); navigate('/profiles') }}
            >
              Manage profiles
            </button>
          </div>
        </div>
      ) : null}
    </>
  )
}
