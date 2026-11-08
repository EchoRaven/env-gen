import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import ProtectedRoute from './components/ProtectedRoute'
import { useAuth } from './context/AuthContext'
import { ToastProvider } from './context/ToastContext'
import AccountPage from './pages/AccountPage'
import BrowseByLanguagesPage from './pages/BrowseByLanguagesPage'
import BrowsePage from './pages/BrowsePage'
import GamesPage from './pages/GamesPage'
import GenrePage from './pages/GenrePage'
import LandingPage from './pages/LandingPage'
import LoginPage from './pages/LoginPage'
import ManageProfilesPage from './pages/ManageProfilesPage'
import MoviesPage from './pages/MoviesPage'
import MyListPage from './pages/MyListPage'
import NewPopularPage from './pages/NewPopularPage'
import NotificationsPage from './pages/NotificationsPage'
import ProfilesPage from './pages/ProfilesPage'
import SearchPage from './pages/SearchPage'
import ShowsPage from './pages/ShowsPage'
import TitlePage from './pages/TitlePage'
import WatchPage from './pages/WatchPage'

function ScrollToTop() {
  const location = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [location.pathname])
  return null
}

export default function App() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    const onUnauthorized = () => { logout(); navigate('/login', { replace: true }) }
    window.addEventListener('nf:unauthorized', onUnauthorized)
    return () => window.removeEventListener('nf:unauthorized', onUnauthorized)
  }, [logout, navigate])

  return (
    <ToastProvider>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/profiles" element={<ProtectedRoute requireProfile={false}><ProfilesPage /></ProtectedRoute>} />
        <Route path="/manage-profiles" element={<ProtectedRoute requireProfile={false}><ManageProfilesPage /></ProtectedRoute>} />
        <Route path="/account" element={<ProtectedRoute requireProfile={false}><AccountPage /></ProtectedRoute>} />
        <Route path="/notifications" element={<ProtectedRoute requireProfile={false}><NotificationsPage /></ProtectedRoute>} />
        <Route path="/watch/:titleId" element={<ProtectedRoute><WatchPage /></ProtectedRoute>} />
        <Route path="/title/:titleId" element={<ProtectedRoute><TitlePage /></ProtectedRoute>} />
        <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
          <Route path="/browse" element={<BrowsePage />} />
          <Route path="/shows" element={<ShowsPage />} />
          <Route path="/movies" element={<MoviesPage />} />
          <Route path="/games" element={<GamesPage />} />
          <Route path="/new" element={<NewPopularPage />} />
          <Route path="/my-list" element={<MyListPage />} />
          <Route path="/browse/languages" element={<BrowseByLanguagesPage />} />
          <Route path="/browse/genre/:genreId" element={<GenrePage />} />
          <Route path="/search" element={<SearchPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  )
}
