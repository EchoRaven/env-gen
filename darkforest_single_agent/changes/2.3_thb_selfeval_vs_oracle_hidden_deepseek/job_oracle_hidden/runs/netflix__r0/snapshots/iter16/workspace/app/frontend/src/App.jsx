import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import BrowsePage from './pages/BrowsePage'
import Landing from './pages/Landing'
import Login from './pages/Login'
import PlayerPage from './pages/PlayerPage'
import Profiles from './pages/Profiles'
import Signup from './pages/Signup'
import TitleDetailPage from './pages/TitleDetailPage'

function ScrollToTop() {
  const location = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [location.pathname])
  return null
}

function LoadingScreen() {
  return (
    <div className="app-loading">
      <img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" />
      <span className="loading-ring" />
    </div>
  )
}

function RequireAuth({ children }) {
  const { token, loading } = useAuth()
  const location = useLocation()
  if (loading) return <LoadingScreen />
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

function RequireProfile({ children }) {
  const { token, loading, activeProfile } = useAuth()
  const location = useLocation()
  if (loading) return <LoadingScreen />
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (!activeProfile) return <Navigate to="/profiles" replace />
  return children
}

function MissingPage() {
  return (
    <div className="missing-page">
      <img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" />
      <h1>Lost your way?</h1>
      <p>We can't find that page. You'll find lots to explore on the home page.</p>
      <a href="/browse">Netflix Home</a>
    </div>
  )
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/profiles" element={<RequireAuth><Profiles /></RequireAuth>} />
        <Route path="/browse" element={<RequireProfile><BrowsePage mode="home" /></RequireProfile>} />
        <Route path="/shows" element={<RequireProfile><BrowsePage mode="shows" /></RequireProfile>} />
        <Route path="/movies" element={<RequireProfile><BrowsePage mode="movies" /></RequireProfile>} />
        <Route path="/games" element={<RequireProfile><BrowsePage mode="games" /></RequireProfile>} />
        <Route path="/new" element={<RequireProfile><BrowsePage mode="new" /></RequireProfile>} />
        <Route path="/my-list" element={<RequireProfile><BrowsePage mode="my-list" /></RequireProfile>} />
        <Route path="/browse/genre/:genreId" element={<RequireProfile><BrowsePage mode="genre" /></RequireProfile>} />
        <Route path="/browse/languages" element={<RequireProfile><BrowsePage mode="languages" /></RequireProfile>} />
        <Route path="/search" element={<RequireProfile><BrowsePage mode="search" /></RequireProfile>} />
        <Route path="/title/:titleId" element={<RequireProfile><TitleDetailPage /></RequireProfile>} />
        <Route path="/watch/:titleId" element={<RequireProfile><PlayerPage /></RequireProfile>} />
        <Route path="*" element={<MissingPage />} />
      </Routes>
    </>
  )
}
