import { useEffect } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useSession } from '../session.jsx'
import Header from './Header.jsx'
import DetailModal from './DetailModal.jsx'

// Authenticated shell: header, page outlet, title-detail modal (?title=ID) and toast.
export default function Layout() {
  const { token, profile, profiles, profileId, toast } = useSession()
  const location = useLocation()
  const titleId = new URLSearchParams(location.search).get('title')
  useEffect(() => { window.scrollTo(0, 0) }, [location.pathname])
  if (!token) return <Navigate to="/login" replace />
  if (!profileId) return <Navigate to="/profiles" replace />
  if (profiles.length === 0) return <div className="boot"><div className="spinner" /></div>
  if (!profile) return <Navigate to="/profiles" replace />
  return (
    <div className="app-shell">
      <Header />
      <main className="page">
        <Outlet />
      </main>
      <footer className="app-footer">
        <p>Catalog data and artwork from TMDB. Trailer clips are royalty-free stock footage.</p>
      </footer>
      {titleId && <DetailModal id={titleId} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  )
}
