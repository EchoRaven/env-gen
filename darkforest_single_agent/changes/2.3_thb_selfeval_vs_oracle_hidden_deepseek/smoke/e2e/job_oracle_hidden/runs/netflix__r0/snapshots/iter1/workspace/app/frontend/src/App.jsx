import React, { useEffect } from 'react'
import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { AppProvider, useApp } from './context'
import Header from './components/Header'
import TitleDetailModal from './components/TitleDetailModal'
import Landing from './pages/Landing'
import AuthPage from './pages/AuthPage'
import Profiles from './pages/Profiles'
import BrowseHome from './pages/BrowseHome'
import Shows from './pages/Shows'
import Movies from './pages/Movies'
import Games from './pages/Games'
import NewPopular from './pages/NewPopular'
import GenreCategory from './pages/GenreCategory'
import Languages from './pages/Languages'
import MyList from './pages/MyList'
import SearchResults from './pages/SearchResults'
import Account from './pages/Account'
import Player from './pages/Player'

function Protected({ children }) {
  const { token, booting } = useApp()
  const location = useLocation()
  if (booting) return <div className="page-loading"><span className="spinner" /> Checking your session…</div>
  if (!token) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}

function AppShell() {
  const [params, setParams] = useSearchParams()
  const titleId = params.get('title')

  useEffect(() => {
    const open = (event) => {
      const next = new URLSearchParams(params)
      next.set('title', String(event.detail))
      setParams(next)
    }
    window.addEventListener('netflix:open-title', open)
    return () => window.removeEventListener('netflix:open-title', open)
  }, [params, setParams])

  const close = () => {
    const next = new URLSearchParams(params)
    next.delete('title')
    setParams(next, { replace: true })
  }

  return (
    <>
      <Header />
      <main className="shell-main"><Outlet /></main>
      {titleId && <TitleDetailModal titleId={titleId} onClose={close} />}
    </>
  )
}

function NotFound() {
  return (
    <div className="not-found">
      <span>Lost your way?</span>
      <h1>That page could not be found.</h1>
      <p>You can return to the catalog and keep browsing.</p>
      <Link className="btn btn-secondary" to="/browse">Netflix Home</Link>
    </div>
  )
}

function AppRoutes() {
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    const goLogin = () => {
      if (location.pathname !== '/login') navigate('/login', { replace: true })
    }
    window.addEventListener('netflix:unauthorized', goLogin)
    return () => window.removeEventListener('netflix:unauthorized', goLogin)
  }, [navigate, location.pathname])

  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/signup" element={<AuthPage mode="register" />} />
      <Route path="/profiles" element={<Protected><Profiles /></Protected>} />
      <Route element={<Protected><AppShell /></Protected>}>
        <Route path="/browse" element={<BrowseHome />} />
        <Route path="/shows" element={<Shows />} />
        <Route path="/movies" element={<Movies />} />
        <Route path="/games" element={<Games />} />
        <Route path="/new" element={<NewPopular />} />
        <Route path="/browse/genre/:genreId" element={<GenreCategory />} />
        <Route path="/browse/languages" element={<Languages />} />
        <Route path="/my-list" element={<MyList />} />
        <Route path="/search" element={<SearchResults />} />
        <Route path="/account" element={<Account />} />
      </Route>
      <Route path="/watch/:titleId" element={<Protected><Player /></Protected>} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AppProvider>
      <AppRoutes />
    </AppProvider>
  )
}
