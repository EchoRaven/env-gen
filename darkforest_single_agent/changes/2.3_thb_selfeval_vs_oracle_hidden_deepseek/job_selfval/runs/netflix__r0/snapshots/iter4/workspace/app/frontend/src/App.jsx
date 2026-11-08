import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useEffect } from 'react'
import { useAuth } from './context/AuthContext.jsx'
import TitleModal from './components/TitleModal.jsx'
import LandingPage from './pages/LandingPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import SignupPage from './pages/SignupPage.jsx'
import ProfilesPage from './pages/ProfilesPage.jsx'
import BrowseHomePage from './pages/BrowseHomePage.jsx'
import ShowsPage from './pages/ShowsPage.jsx'
import MoviesPage from './pages/MoviesPage.jsx'
import GamesPage from './pages/GamesPage.jsx'
import NewAndPopularPage from './pages/NewAndPopularPage.jsx'
import GenreCategoryPage from './pages/GenreCategoryPage.jsx'
import MyListPage from './pages/MyListPage.jsx'
import SearchPage from './pages/SearchPage.jsx'
import BrowseByLanguagesPage from './pages/BrowseByLanguagesPage.jsx'
import PlayerPage from './pages/PlayerPage.jsx'
import AccountPage from './pages/AccountPage.jsx'
import NotFoundPage from './pages/NotFoundPage.jsx'
import HelpPage from './pages/HelpPage.jsx'

function Screen({ children }) {
  const { booting } = useAuth()
  if (booting) {
    return <div className="boot-screen"><img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" /></div>
  }
  return children
}

function RequireAuth({ children }) {
  const { token, booting } = useAuth()
  const location = useLocation()
  if (booting) return <Screen>{null}</Screen>
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

function RequireProfile({ children }) {
  const { token, booting, activeProfile, profiles } = useAuth()
  if (booting) return <Screen>{null}</Screen>
  if (!token) return <Navigate to="/login" replace />
  if (!activeProfile && profiles.length) return <Navigate to="/profiles" replace />
  return children
}

function TitleRoute() {
  const { id } = useParams()
  const navigate = useNavigate()
  useEffect(() => {
    navigate(`/browse?title=${id}`, { replace: true })
  }, [id, navigate])
  return null
}

export default function App() {
  return (
    <Screen>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="/profiles" element={<RequireAuth><ProfilesPage /></RequireAuth>} />
        <Route path="/browse" element={<RequireProfile><BrowseHomePage /></RequireProfile>} />
        <Route path="/shows" element={<RequireProfile><ShowsPage /></RequireProfile>} />
        <Route path="/movies" element={<RequireProfile><MoviesPage /></RequireProfile>} />
        <Route path="/games" element={<RequireProfile><GamesPage /></RequireProfile>} />
        <Route path="/new" element={<RequireProfile><NewAndPopularPage /></RequireProfile>} />
        <Route path="/browse/genre/:genreId" element={<RequireProfile><GenreCategoryPage /></RequireProfile>} />
        <Route path="/browse/languages" element={<RequireProfile><BrowseByLanguagesPage /></RequireProfile>} />
        <Route path="/my-list" element={<RequireProfile><MyListPage /></RequireProfile>} />
        <Route path="/search" element={<RequireProfile><SearchPage /></RequireProfile>} />
        <Route path="/account" element={<RequireAuth><AccountPage /></RequireAuth>} />
        <Route path="/title/:id" element={<RequireProfile><TitleRoute /></RequireProfile>} />
        <Route path="/watch/:id" element={<RequireProfile><PlayerPage /></RequireProfile>} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      <TitleModal />
    </Screen>
  )
}
