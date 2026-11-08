import React, { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useApp } from '../context'
import { api } from '../api'
import Avatar from './Avatar'
import Icon from './Icon'
import Logo from './Logo'

const navItems = [
  ['Home', '/browse'],
  ['Shows', '/shows'],
  ['Movies', '/movies'],
  ['Games', '/games'],
  ['New & Popular', '/new'],
  ['My List', '/my-list'],
  ['Browse by Languages', '/browse/languages'],
]

export default function Header() {
  const { profile, logout } = useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [menu, setMenu] = useState(null)
  const [notifications, setNotifications] = useState(null)
  const rootRef = useRef(null)
  const searchRef = useRef(null)
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 18)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    const close = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setMenu(null)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  useEffect(() => {
    setMenu(null)
  }, [location.pathname, location.search])

  useEffect(() => {
    if (searchOpen) setTimeout(() => searchRef.current?.focus(), 30)
  }, [searchOpen])

  const submitSearch = (event) => {
    event.preventDefault()
    const value = query.trim()
    if (!value) {
      searchRef.current?.focus()
      return
    }
    navigate(`/search?q=${encodeURIComponent(value)}`)
    setMenu(null)
  }

  const toggleNotifications = () => {
    if (menu === 'notifications') { setMenu(null); return }
    setMenu('notifications')
    if (notifications === null) {
      api('/api/notifications')
        .then(list => setNotifications(Array.isArray(list) ? list : []))
        .catch(() => setNotifications([]))
    }
  }

  const signOut = () => {
    logout()
    navigate('/')
  }

  return (
    <header ref={rootRef} className={`site-header ${scrolled ? 'is-scrolled' : ''}`}>
      <div className="header-left">
        <Logo />
        <nav className="primary-nav" aria-label="Primary">
          {navItems.map(([label, to]) => (
            <NavLink key={to} to={to} end={to === '/browse'} className={({ isActive }) => isActive ? 'active' : ''}>
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="header-right">
        <form className={`header-search ${searchOpen ? 'open' : ''}`} onSubmit={submitSearch}>
          <input
            ref={searchRef}
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="Titles, genres, people"
            aria-label="Search titles"
            onBlur={() => { if (!query) setSearchOpen(false) }}
          />
          <button type="button" className="icon-button" aria-label="Search" onClick={() => {
            if (searchOpen && query.trim()) {
              navigate(`/search?q=${encodeURIComponent(query.trim())}`)
            } else {
              setSearchOpen(value => !value)
            }
          }}>
            <Icon name="search" size={24} />
          </button>
        </form>

        <div className="header-menu-wrap">
          <button
            type="button"
            className="icon-button"
            aria-label="Notifications"
            aria-expanded={menu === 'notifications'}
            onClick={toggleNotifications}
          >
            <Icon name="bell" size={24} />
          </button>
          {menu === 'notifications' && (
            <div className="header-popover notification-popover">
              <h3>Notifications</h3>
              {notifications === null ? (
                <div className="empty-popover"><span className="spinner" /><p>Checking for notifications…</p></div>
              ) : notifications.length === 0 ? (
                <div className="empty-popover">
                  <Icon name="bell" size={32} />
                  <p>No new notifications</p>
                  <span>New releases and recommendations will appear here.</span>
                </div>
              ) : (
                <div className="notification-list">
                  {notifications.map(item => <div key={item.id}><strong>{item.title}</strong><span>{item.message}</span></div>)}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="header-menu-wrap">
          <button
            type="button"
            className="profile-trigger"
            aria-label="Profile menu"
            aria-expanded={menu === 'profile'}
            onClick={() => setMenu(menu === 'profile' ? null : 'profile')}
          >
            <Avatar profile={profile} size={34} />
            <span className="caret"><Icon name="chevron-down" size={16} /></span>
          </button>
          {menu === 'profile' && (
            <div className="header-popover account-popover">
              <div className="popover-profiles">
                {profile && (
                  <div className="popover-current-profile">
                    <Avatar profile={profile} size={34} />
                    <span>{profile.name}</span>
                  </div>
                )}
                <button type="button" onClick={() => { setMenu(null); navigate('/profiles') }}>
                  Manage Profiles
                </button>
              </div>
              <button type="button" onClick={() => { setMenu(null); navigate('/account') }}>Account</button>
              <button type="button" onClick={() => { setMenu(null); navigate('/account') }}>Help Centre</button>
              <button type="button" className="signout" onClick={signOut}>Sign out of Netflix</button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
