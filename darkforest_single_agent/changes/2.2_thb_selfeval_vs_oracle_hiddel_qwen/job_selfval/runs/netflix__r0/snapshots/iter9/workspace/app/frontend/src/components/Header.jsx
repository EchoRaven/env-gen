import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useApp } from "../store";
import { openTitleModal } from "../App";
import SearchOverlay from "./SearchOverlay";
import AccountMenuCard from "./AccountMenuCard";

const AVATAR_GRADIENTS = [
  "from-blue-500 to-purple-600",
  "from-green-500 to-teal-600",
  "from-red-500 to-orange-600",
  "from-yellow-500 to-amber-600",
  "from-pink-500 to-rose-600",
  "from-indigo-500 to-violet-600",
  "from-cyan-500 to-sky-600",
  "from-lime-500 to-emerald-600"
];
export function avatarClass(avatar) {
  const n = parseInt(avatar, 10);
  const i = Math.abs(Number.isFinite(n) ? n : 0) % AVATAR_GRADIENTS.length;
  return AVATAR_GRADIENTS[i];
}

const NAV = [
  { to: "/browse", label: "Home" },
  { to: "/shows", label: "Shows" },
  { to: "/movies", label: "Movies" },
  { to: "/games", label: "Games" },
  { to: "/new", label: "New & Popular" },
  { to: "/my-list", label: "My List" },
  { to: "/browse/languages", label: "Browse by Languages" }
];

export default function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const { profile, user, logout } = useApp();
  const loc = useLocation();
  const menuRef = useRef(null);
  const bellRef = useRef(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll);
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const onClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
      if (bellRef.current && !bellRef.current.contains(e.target)) setBellOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
    setBellOpen(false);
    setSearchOpen(false);
  }, [loc.pathname]);

  return (
    <header
      className={`fixed top-0 left-0 right-0 z-40 transition-colors duration-300 ${
        scrolled ? "bg-nfg" : "bg-gradient-to-b from-black/70 to-transparent"
      }`}
    >
      <div className="flex items-center h-[84px] px-[3.5vw] gap-8">
        <Link to="/browse" aria-label="Netflix home" className="shrink-0">
          <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-[20px]" />
        </Link>
        <nav className="hidden lg:flex items-center gap-4 text-[13px] text-[#e5e5e5] flex-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                isActive ? "text-white font-semibold" : "hover:text-white transition-colors"
              }
              end={n.to === "/browse"}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-4 ml-auto">
          <button
            onClick={() => setSearchOpen((v) => !v)}
            aria-label="Search titles"
            className="hover:scale-110 transition-transform"
          >
            <img src="/assets/icons/search.svg" alt="" className="w-5 h-5 invert" />
          </button>
          <div className="relative hidden md:block" ref={bellRef}>
            <button onClick={() => setBellOpen((v) => !v)} aria-label="Notifications" className="relative">
              <img src="/assets/icons/bell.svg" alt="" className="w-5 h-5 invert" />
            </button>
            {bellOpen && (
              <div className="absolute right-0 top-8 w-72 bg-black/95 border border-[#414244] text-sm shadow-xl">
                <div className="px-4 py-3 border-b border-[#333] font-semibold">Notifications</div>
                <div className="px-4 py-8 text-[#999]">No new notifications</div>
              </div>
            )}
          </div>
          <div className="relative flex items-center" ref={menuRef}>
            <button
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="Account menu"
              className="flex items-center gap-1.5 group"
            >
              <span
                className={`w-9 h-9 rounded bg-gradient-to-br ${avatarClass(profile ? profile.avatar : 0)} flex items-center justify-center text-[15px] font-bold`}
              >
                {(profile ? profile.name : (user ? user.name : "N")).charAt(0).toUpperCase()}
              </span>
              <img src="/assets/icons/chevron-down.svg" alt="" className="w-3 h-3 invert group-hover:rotate-180 transition-transform" />
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-[64px] w-[280px] bg-[#232323] border border-[#3a3a3a] rounded-sm shadow-2xl text-[#e5e5e5]">
                <div className="px-5 pt-[18px] pb-4 flex items-center gap-3">
                  <span
                    className={`w-9 h-9 rounded bg-gradient-to-br ${avatarClass(profile ? profile.avatar : 0)} flex items-center justify-center text-[15px] font-bold text-white shrink-0`}
                  >
                    {(profile ? profile.name : (user ? user.name : "N")).charAt(0).toUpperCase()}
                  </span>
                  <span className="text-[15px] text-white truncate">
                    {profile ? profile.name : "—"}
                  </span>
                </div>
                <button
                  onClick={() => { setMenuOpen(false); window.location.href = "/profiles"; }}
                  className="w-full flex items-center gap-4 px-5 h-[52px] text-[15px] text-left hover:bg-[#2e2e2e] transition-colors"
                >
                  <svg viewBox="0 0 24 24" className="w-5 h-5 shrink-0" fill="none" stroke="#e5e5e5" strokeWidth="1.6">
                    <circle cx="10" cy="8" r="3.4" />
                    <path d="M4.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
                    <path d="M15.5 5.6a3.4 3.4 0 0 1 0 5" />
                    <path d="M16.8 14.4c1.9.8 2.7 2.4 2.7 4.6" />
                  </svg>
                  <span>Manage Profiles</span>
                </button>
                <button
                  onClick={() => { setMenuOpen(false); window.location.href = "/account"; }}
                  className="w-full flex items-center gap-4 px-5 h-[52px] text-[15px] text-left hover:bg-[#2e2e2e] transition-colors"
                >
                  <svg viewBox="0 0 24 24" className="w-5 h-5 shrink-0" fill="none" stroke="#e5e5e5" strokeWidth="1.6">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1" />
                  </svg>
                  <span>Account Settings</span>
                </button>
                <button
                  onClick={() => { logout(); window.location.href = "/"; }}
                  className="w-full flex items-center gap-4 px-5 h-[52px] text-[15px] text-left hover:bg-[#2e2e2e] transition-colors"
                >
                  <svg viewBox="0 0 24 24" className="w-5 h-5 shrink-0" fill="none" stroke="#e5e5e5" strokeWidth="1.6">
                    <path d="M14 4H6v16h8" />
                    <path d="M10 12h11M18 8.5 21.5 12 18 15.5" />
                  </svg>
                  <span>Sign out</span>
                </button>
                <AccountMenuCard
                  onPlay={(id) => { setMenuOpen(false); window.location.href = `/watch/${id}`; }}
                />
              </div>
            )}
          </div>
        </div>
      </div>
      {searchOpen && <SearchOverlay onClose={() => setSearchOpen(false)} />}
    </header>
  );
}
