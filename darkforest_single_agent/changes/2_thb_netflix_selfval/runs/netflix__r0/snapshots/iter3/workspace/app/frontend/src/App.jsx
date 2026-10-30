import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
import Profiles from './pages/Profiles.jsx'
import BrowseHome from './pages/BrowseHome.jsx'
import Shows from './pages/Shows.jsx'
import Movies from './pages/Movies.jsx'
import Games from './pages/Games.jsx'
import NewAndPopular from './pages/NewAndPopular.jsx'
import GenreCategory from './pages/GenreCategory.jsx'
import MyList from './pages/MyList.jsx'
import BrowseByLanguages from './pages/BrowseByLanguages.jsx'
import Search from './pages/Search.jsx'
import Account from './pages/Account.jsx'
import Player from './pages/Player.jsx'
import TitlePage from './pages/TitlePage.jsx'
import NotFound from './pages/NotFound.jsx'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Login signup />} />
      <Route path="/profiles" element={<Profiles />} />
      <Route path="/watch/:titleId" element={<Player />} />
      <Route element={<Layout />}>
        <Route path="/browse" element={<BrowseHome />} />
        <Route path="/shows" element={<Shows />} />
        <Route path="/movies" element={<Movies />} />
        <Route path="/games" element={<Games />} />
        <Route path="/new" element={<NewAndPopular />} />
        <Route path="/browse/genre/:genreId" element={<GenreCategory />} />
        <Route path="/my-list" element={<MyList />} />
        <Route path="/browse/languages" element={<BrowseByLanguages />} />
        <Route path="/search" element={<Search />} />
        <Route path="/account" element={<Account />} />
        <Route path="/title/:titleId" element={<TitlePage />} />
      </Route>
      <Route path="/home" element={<Navigate to="/browse" replace />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
