import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useStore } from './store';
import Layout from './components/Layout';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Profiles from './pages/Profiles';
import Home from './pages/Home';
import Shows from './pages/Shows';
import Movies from './pages/Movies';
import Games from './pages/Games';
import NewPopular from './pages/NewPopular';
import GenreCategory from './pages/GenreCategory';
import MyList from './pages/MyList';
import Languages from './pages/Languages';
import Search from './pages/Search';
import Player from './pages/Player';
import Account from './pages/Account';
import NotFound from './pages/NotFound';

function RequireAuth({ children }) {
  const { token } = useStore();
  const loc = useLocation();
  if (!token) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return children;
}

function RequireProfile({ children }) {
  const { token, profile, profilesLoaded } = useStore();
  const loc = useLocation();
  if (!token) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  if (!profilesLoaded) return <div className="profiles-loading"><div className="spinner" /></div>;
  if (!profile) return <Profiles redirectTo={loc.pathname + loc.search} />;
  return children;
}

function PublicOnly({ children }) {
  const { token } = useStore();
  if (token) return <Navigate to="/browse" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<PublicOnly><Landing /></PublicOnly>} />
      <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/signup" element={<PublicOnly><Signup /></PublicOnly>} />
      <Route path="/profiles" element={<RequireAuth><Profiles /></RequireAuth>} />
      <Route path="/profiles/manage" element={<RequireAuth><Profiles manage /></RequireAuth>} />
      <Route path="/watch/:titleId" element={<RequireProfile><Player /></RequireProfile>} />
      <Route element={<RequireProfile><Layout /></RequireProfile>}>
        <Route path="/browse" element={<Home />} />
        <Route path="/shows" element={<Shows />} />
        <Route path="/movies" element={<Movies />} />
        <Route path="/games" element={<Games />} />
        <Route path="/new" element={<NewPopular />} />
        <Route path="/browse/genre/:genreId" element={<GenreCategory />} />
        <Route path="/my-list" element={<MyList />} />
        <Route path="/browse/languages" element={<Languages />} />
        <Route path="/search" element={<Search />} />
        <Route path="/account" element={<Account />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
