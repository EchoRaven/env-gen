import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import Icon from './Icon';
import Avatar from './Avatar';
import { useStore } from '../store';
import { API } from '../api';

const NAV = [
  ['/browse', 'Home'],
  ['/shows', 'Shows'],
  ['/movies', 'Movies'],
  ['/games', 'Games'],
  ['/new', 'New & Popular'],
  ['/my-list', 'My List'],
  ['/browse/languages', 'Browse by Languages'],
];

function useOutsideClose(open, setOpen) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open, setOpen]);
  return ref;
}

function SearchBox() {
  const { refresh } = useStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const onSearch = location.pathname === '/search';
  const [open, setOpen] = useState(onSearch);
  const [q, setQ] = useState(onSearch ? params.get('q') || '' : '');
  const inputRef = useRef(null);
  const ref = useOutsideClose(open && !q, setOpen);

  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);

  const change = (v) => {
    setQ(v);
    if (v.trim()) navigate(`/search?q=${encodeURIComponent(v)}`, { replace: onSearch });
    else if (onSearch) navigate('/browse');
  };

  return (
    <div className={`search-box ${open ? 'open' : ''}`} ref={ref}>
      <button className="icon-btn" aria-label="Search" data-testid="search-toggle" onClick={() => { if (open && q) { refresh(); inputRef.current?.focus(); } else setOpen((o) => !o); }}>
        <Icon name="nf-search" size={26} />
      </button>
      {open && (
        <>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => change(e.target.value)}
            placeholder="Titles, genres"
            aria-label="Search titles and genres"
          />
          {q && (
            <button className="icon-btn clear" aria-label="Clear search" onClick={() => change('')}>
              <Icon name="nf-close" size={14} />
            </button>
          )}
        </>
      )}
    </div>
  );
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(null);
  const ref = useOutsideClose(open, setOpen);
  const [, setParams] = useSearchParams();
  const toggle = async () => {
    setOpen((o) => !o);
    if (!items) {
      try { setItems((await API.trending({ limit: 6 })).filter((t) => t.year >= 2026)); } catch { setItems([]); }
    }
  };
  return (
    <div className="notif" ref={ref}>
      <button className="icon-btn" aria-label="Notifications" onClick={toggle}>
        <Icon name="nf-bell" size={26} />
        {items && items.length > 0 && !open && <span className="notif-dot" />}
      </button>
      {open && (
        <div className="dropdown notif-menu" role="menu">
          {items === null && <div className="notif-empty">Loading…</div>}
          {items && items.length === 0 && <div className="notif-empty">No recent notifications</div>}
          {items && items.map((t) => (
            <button key={t.id} className="notif-item" onClick={() => { setOpen(false); setParams((p) => { p.set('title', t.id); return p; }); }}>
              <img src={t.backdrop} alt="" />
              <span>
                <b>New Arrival</b>
                <span>{t.name}</span>
                <small>{t.year} · {t.genre}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AccountMenu() {
  const { profile, profiles, selectProfile, logout } = useStore();
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(open, setOpen);
  const navigate = useNavigate();
  const others = profiles.filter((p) => p.id !== profile?.id);
  return (
    <div className="account" ref={ref}>
      <button className="account-btn" aria-label="Account menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Avatar avatar={profile?.avatar} size={36} />
        <span className={`caret ${open ? 'up' : ''}`} />
      </button>
      {open && (
        <div className="dropdown account-menu" role="menu">
          {others.map((p) => (
            <button key={p.id} className="menu-item" onClick={() => { setOpen(false); selectProfile(p); navigate('/browse'); }}>
              <Avatar avatar={p.avatar} size={32} /> <span>{p.name}</span>
            </button>
          ))}
          <button className="menu-item" onClick={() => { setOpen(false); navigate('/profiles/manage'); }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M4 20l4-1 11-11-3-3L5 16l-1 4z" /><path d="M14 6l3 3" /></svg>
            <span>Manage Profiles</span>
          </button>
          <button className="menu-item" onClick={() => { setOpen(false); navigate('/account'); }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="8" r="4" /><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6" /></svg>
            <span>Account</span>
          </button>
          <button className="menu-item" onClick={() => { setOpen(false); navigate('/profiles'); }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M8 21h8" /></svg>
            <span>Switch Profile</span>
          </button>
          <div className="menu-sep" />
          <button className="menu-item signout" onClick={() => { logout(); navigate('/'); }}>Sign out of Netflix</button>
        </div>
      )}
    </div>
  );
}

export default function Header() {
  const [scrolled, setScrolled] = useState(false);
  const { profiles, profile, selectProfile, refresh } = useStore();
  const navigate = useNavigate();
  const location = useLocation();
  // Clicking the link of the page you're on reloads its rails and scrolls to the top.
  const onNav = (to) => () => { if (location.pathname === to) refresh(); };
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 10);
    on();
    window.addEventListener('scroll', on);
    return () => window.removeEventListener('scroll', on);
  }, []);
  const kids = profiles.find((p) => p.is_kids);
  const goKids = () => {
    if (kids && profile?.id !== kids.id) { selectProfile(kids); navigate('/browse'); } else navigate('/profiles');
  };
  return (
    <header className={`main-header ${scrolled ? 'scrolled' : ''}`}>
      <Link to="/browse" className="logo" aria-label="Netflix home" onClick={onNav('/browse')}>
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" />
      </Link>
      <nav className="primary-nav">
        {NAV.map(([to, label]) => (
          <NavLink key={to} to={to} end onClick={onNav(to)} className={({ isActive }) => (isActive ? 'active' : '')}>{label}</NavLink>
        ))}
      </nav>
      <div className="secondary-nav">
        <SearchBox />
        <Notifications />
        <button className="kids-link" onClick={goKids} aria-label={kids && profile?.id === kids.id ? 'Kids profile active' : 'Switch to Kids profile'}>
          <Avatar avatar="kids" size={36} /> <span>Kids</span>
        </button>
        <AccountMenu />
      </div>
    </header>
  );
}
