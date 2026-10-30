import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useSession } from '../session.jsx'
import { CaretDown, Icon, PencilIcon, UserIcon } from '../icons.jsx'
import Avatar from './Avatar.jsx'

const NAV = [
  ['/browse', 'Home'], ['/shows', 'Shows'], ['/movies', 'Movies'], ['/games', 'Games'],
  ['/new', 'New & Popular'], ['/my-list', 'My List'], ['/browse/languages', 'Browse by Languages'],
]

function useOutside(ref, onOut) {
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onOut() }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [ref, onOut])
}

function SearchBox() {
  const navigate = useNavigate()
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  const onSearch = location.pathname === '/search'
  const [open, setOpen] = useState(onSearch)
  const [q, setQ] = useState(onSearch ? params.get('q') || '' : '')
  const input = useRef(null)
  const box = useRef(null)
  useOutside(box, () => { if (!q) setOpen(false) })

  useEffect(() => { if (open) input.current?.focus() }, [open])

  const change = (v) => {
    setQ(v)
    clearTimeout(change._t)
    change._t = setTimeout(() => {
      if (v.trim()) navigate(`/search?q=${encodeURIComponent(v.trim())}`, { replace: onSearch })
      else if (onSearch) navigate('/browse')
    }, 300)
  }

  return (
    <div ref={box} className={`search-box ${open ? 'open' : ''}`}>
      <button className="icon-btn" aria-label="Search" onClick={() => setOpen(true)}>
        <Icon name="search" size={26} />
      </button>
      {open && (
        <input ref={input} value={q} placeholder="Titles, people, genres"
          onChange={(e) => change(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') { setQ(''); setOpen(false) } }} />
      )}
      {open && q && (
        <button className="search-clear" aria-label="Clear search" onClick={() => change('')}>
          <Icon name="close" size={16} />
        </button>
      )}
    </div>
  )
}

function Notifications() {
  const { openTitle, profileId } = useSession()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState(null)
  const ref = useRef(null)
  useOutside(ref, () => setOpen(false))
  useEffect(() => {
    if (!open) return
    api.titles({ sort: 'new', limit: 6 }).then((r) => setItems(r.items)).catch(() => setItems([]))
  }, [open, profileId])
  return (
    <div className="notif" ref={ref}>
      <button className="icon-btn" aria-label="Notifications" onClick={() => setOpen((o) => !o)}>
        <Icon name="bell" size={26} />
      </button>
      {open && (
        <div className="dropdown notif-menu">
          <div className="notif-head">New Arrivals</div>
          {items === null && <div className="notif-empty">Loading…</div>}
          {items && items.length === 0 && <div className="notif-empty">No notifications</div>}
          {items && items.map((t) => (
            <button key={t.id} className="notif-item" onClick={() => { setOpen(false); openTitle(t.id) }}>
              <img src={t.backdrop} alt="" />
              <span>
                <b>New Arrival</b>
                <span>{t.name}</span>
                <small>{t.year} · {t.kind === 'series' ? 'Series' : 'Movie'}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ProfileMenu() {
  const { profiles, profile, selectProfile, logout } = useSession()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const timer = useRef(null)
  useOutside(ref, () => setOpen(false))
  const others = profiles.filter((p) => !profile || p.id !== profile.id)
  const enter = () => { clearTimeout(timer.current); setOpen(true) }
  const leave = () => { timer.current = setTimeout(() => setOpen(false), 250) }
  return (
    <div className="profile-menu" ref={ref} onMouseEnter={enter} onMouseLeave={leave}>
      <button className="profile-btn" aria-label="Account menu" aria-expanded={open} onClick={() => setOpen(true)}>
        <Avatar avatar={profile?.avatar} size={36} />
        <span className={`caret ${open ? 'up' : ''}`}><CaretDown /></span>
      </button>
      {open && (
        <div className="dropdown account-menu">
          {others.map((p) => (
            <button key={p.id} className="am-item" onClick={() => { setOpen(false); selectProfile(p); navigate('/browse') }}>
              <Avatar avatar={p.avatar} size={36} /> <span>{p.name}</span>
            </button>
          ))}
          <button className="am-item" onClick={() => { setOpen(false); navigate('/profiles?manage=1') }}>
            <span className="am-ico"><PencilIcon size={26} /></span><span>Manage Profiles</span>
          </button>
          <button className="am-item" onClick={() => { setOpen(false); navigate('/account') }}>
            <span className="am-ico"><UserIcon size={26} /></span><span>Account</span>
          </button>
          <div className="am-sep" />
          <button className="am-item am-signout" onClick={() => { setOpen(false); logout() }}>
            Sign out of Netflix
          </button>
        </div>
      )}
    </div>
  )
}

export default function Header() {
  const { profiles, profile, selectProfile } = useSession()
  const navigate = useNavigate()
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const h = () => setScrolled(window.scrollY > 10)
    h()
    window.addEventListener('scroll', h, { passive: true })
    return () => window.removeEventListener('scroll', h)
  }, [])
  const kids = profiles.find((p) => p.is_kids && (!profile || p.id !== profile.id))

  return (
    <header className={`app-header ${scrolled ? 'scrolled' : ''}`}>
      <Link to="/browse" className="wordmark-link" aria-label="Netflix home">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="wordmark" />
      </Link>
      <nav className="primary-nav">
        {NAV.map(([to, label]) => (
          <NavLink key={to} to={to} end className={({ isActive }) => `nav-pill ${isActive ? 'active' : ''}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="header-right">
        <SearchBox />
        <Notifications />
        {kids && (
          <button className="kids-link" onClick={() => { selectProfile(kids); navigate('/browse') }}>
            <Avatar avatar="kids" size={36} /> <span>Kids</span>
          </button>
        )}
        {profile?.is_kids && (
          <button className="kids-link" onClick={() => navigate('/profiles')}>
            <span>Exit Kids</span>
          </button>
        )}
        <ProfileMenu />
      </div>
    </header>
  )
}
