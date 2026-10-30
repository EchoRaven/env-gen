import { useCallback } from 'react';
import { Link, Outlet, useSearchParams } from 'react-router-dom';
import Header from './Header';
import TitleModal from './TitleModal';
import { useStore } from '../store';

export default function Layout() {
  const [params, setParams] = useSearchParams();
  const { toast, refreshKey } = useStore();
  const titleId = params.get('title');
  const close = useCallback(() => setParams((p) => { p.delete('title'); return p; }), [setParams]);
  return (
    <div className="app-shell">
      <Header />
      <main className="app-main">
        <div key={refreshKey}>
          <Outlet />
        </div>
      </main>
      <footer className="app-footer">
        <div className="footer-links">
          <Link to="/browse">Home</Link>
          <Link to="/shows">TV Shows</Link>
          <Link to="/movies">Movies</Link>
          <Link to="/new">New &amp; Popular</Link>
          <Link to="/my-list">My List</Link>
          <Link to="/account">Account</Link>
          <Link to="/profiles/manage">Manage Profiles</Link>
          <Link to="/browse/languages">Browse by Languages</Link>
        </div>
        <p className="footer-note">Netflix clone · catalog data from TMDB · for local demo use only</p>
      </footer>
      {titleId && <TitleModal id={titleId} onClose={close} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
