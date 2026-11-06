import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { getToken, getStoredProfile } from './lib/api'
import { useApp } from './state/AppContext'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Profiles from './pages/Profiles'
import Browse from './pages/Browse'
import Shows from './pages/Shows'
import Movies from './pages/Movies'
import Games from './pages/Games'
import NewPopular from './pages/NewPopular'
import GenreCategory from './pages/GenreCategory'
import MyListPage from './pages/MyListPage'
import LanguagesPage from './pages/LanguagesPage'
import SearchPage from './pages/SearchPage'
import PlayerPage from './pages/PlayerPage'
import AccountPage from './pages/AccountPage'
import NotFound from './pages/NotFound'
import TitleModalHost from './components/TitleModalHost'

function LoginGate() {
  const { ready, profiles } = useApp()
  if (!ready) return null
  if (getToken() && profiles.length > 0) return <Navigate to="/profiles" replace />
  return <Login />
}

function RequireAuth({ children }) {
  const { ready, profile } = useApp()
  const loc = useLocation()
  if (!ready) return <div className="page-pad" style={{ minHeight: '100vh' }} />
  if (!getToken()) return <Navigate to="/login" state={{ from: loc.pathname }} replace />
  if (getStoredProfile() == null) return <Navigate to="/profiles" replace />
  return children
}

export default function App() {
  const { ready } = useApp()
  const loc = useLocation()
  if (!ready) return <div style={{ minHeight: '100vh', background: '#141414' }} />
  const authed = !!getToken()
  return (
    <>
      <Routes>
        <Route path="/" element={authed ? <Navigate to="/browse" replace /> : <Landing />} />
        <Route path="/login" element={<LoginGate />} />
        <Route path="/profiles" element={authed ? <Profiles /> : <Navigate to="/login" replace />} />
        <Route path="/browse" element={<RequireAuth><Browse /></RequireAuth>} />
        <Route path="/shows" element={<RequireAuth><Shows /></RequireAuth>} />
        <Route path="/movies" element={<RequireAuth><Movies /></RequireAuth>} />
        <Route path="/games" element={<RequireAuth><Games /></RequireAuth>} />
        <Route path="/new" element={<RequireAuth><NewPopular /></RequireAuth>} />
        <Route path="/browse/genre/:genreId" element={<RequireAuth><GenreCategory /></RequireAuth>} />
        <Route path="/mylist" element={<RequireAuth><MyListPage /></RequireAuth>} />
        <Route path="/browse/languages" element={<RequireAuth><LanguagesPage /></RequireAuth>} />
        <Route path="/search" element={<RequireAuth><SearchPage /></RequireAuth>} />
        <Route path="/account" element={<RequireAuth><AccountPage /></RequireAuth>} />
        <Route path="/watch/:titleId" element={<RequireAuth><PlayerPage /></RequireAuth>} />
        <Route path="*" element={authed ? <RequireAuth><NotFound /></RequireAuth> : <Navigate to="/" replace />} />
      </Routes>
      <TitleModalHost />
    </>
  )
}
