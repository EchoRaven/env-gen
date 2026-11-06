import { useEffect, useState } from "react";
import { Routes, Route, Navigate, Outlet, useLocation } from "react-router-dom";
import { useApp } from "./store";
import { getToken } from "./api";
import Header from "./components/Header";
import TitleModal from "./components/TitleModal";
import RateDialog from "./components/RateDialog";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Profiles from "./pages/Profiles";
import Home from "./pages/Home";
import Shows from "./pages/Shows";
import Movies from "./pages/Movies";
import Games from "./pages/Games";
import NewPopular from "./pages/NewPopular";
import GenreCategory from "./pages/GenreCategory";
import MyList from "./pages/MyList";
import BrowseLanguages from "./pages/BrowseLanguages";
import PlayerPage from "./pages/PlayerPage";
import NotFound from "./pages/NotFound";
import Account from "./pages/Account";

export const openTitleModal = (id) => {
  window.dispatchEvent(new CustomEvent("nf:open-title", { detail: { id } }));
};

function Guard({ children, needProfile = true }) {
  const { profile, booted } = useApp();
  const loc = useLocation();
  if (!booted) return <div className="min-h-screen bg-nfg" />;
  if (!getToken()) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (needProfile && !profile) return <Navigate to="/profiles" replace />;
  return children;
}

function BrowseLayout() {
  const { profile } = useApp();
  const [modalId, setModalId] = useState(null);
  const [rateId, setRateId] = useState(null);

  useEffect(() => {
    const onOpen = (e) => setModalId(e.detail.id);
    const onRate = (e) => setRateId(e.detail.id);
    window.addEventListener("nf:open-title", onOpen);
    window.addEventListener("nf:rate", onRate);
    return () => {
      window.removeEventListener("nf:open-title", onOpen);
      window.removeEventListener("nf:rate", onRate);
    };
  }, []);

  useEffect(() => {
    if (!modalId) return;
    const onKey = (e) => e.key === "Escape" && setModalId(null);
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [modalId]);

  return (
    <div className="min-h-screen bg-nfg">
      <Header />
      <main>
        <Outlet />
      </main>
      {modalId && profile && <TitleModal id={modalId} onClose={() => setModalId(null)} />}
      {rateId && profile && <RateDialog titleId={rateId} onClose={() => setRateId(null)} />}
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/profiles" element={<Guard needProfile={false}><Profiles /></Guard>} />
      <Route element={<Guard><BrowseLayout /></Guard>}>
        <Route path="/browse" element={<Home />} />
        <Route path="/shows" element={<Shows />} />
        <Route path="/movies" element={<Movies />} />
        <Route path="/games" element={<Games />} />
        <Route path="/new" element={<NewPopular />} />
        <Route path="/browse/genre/:genreId" element={<GenreCategory />} />
        <Route path="/browse/languages" element={<BrowseLanguages />} />
        <Route path="/my-list" element={<MyList />} />
        <Route path="/account" element={<Account />} />
      </Route>
      <Route path="/watch/:titleId" element={<Guard needProfile={false}><PlayerPage /></Guard>} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
