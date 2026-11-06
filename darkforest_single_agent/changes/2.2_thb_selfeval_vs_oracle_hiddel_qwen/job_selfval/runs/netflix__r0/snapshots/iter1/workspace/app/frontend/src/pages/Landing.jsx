import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

const COLLAGE = [
  "/assets/backdrops/movie_1003596.jpg",
  "/assets/backdrops/tv_37854.jpg",
  "/assets/backdrops/movie_1339713.jpg",
  "/assets/backdrops/tv_279323.jpg",
  "/assets/backdrops/movie_1108427.jpg",
  "/assets/backdrops/movie_1275779.jpg",
  "/assets/backdrops/tv_12415.jpg",
  "/assets/backdrops/movie_1081003.jpg"
];

export default function Landing() {
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const nav = useNavigate();

  const start = () => {
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setErr("Please enter a valid email address.");
      return;
    }
    setErr("");
    nav(`/register?email=${encodeURIComponent(email)}`);
  };

  return (
    <div className="relative min-h-screen bg-nfg overflow-hidden">
      <div
        className="absolute inset-0 grid grid-cols-4 grid-rows-2 opacity-40"
        style={{ backgroundImage: "" }}
      >
        {COLLAGE.map((p, i) => (
          <div key={i} className="w-full h-full">
            <img src={p} alt="" className="w-full h-full object-cover" />
          </div>
        ))}
      </div>
      <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-black/40 to-[#141414]" />

      <header className="relative z-10 flex items-center justify-between px-6 md:px-[4vw] h-[72px]">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-6 md:h-8" />
        <Link
          to="/login"
          className="bg-white text-black text-sm font-semibold rounded px-4 py-1.5 hover:bg-white/80"
        >
          Sign In
        </Link>
      </header>

      <div className="relative z-10 px-6 md:px-[4vw] pt-[14vh] pb-[8vh] max-w-3xl">
        <h1 className="text-3xl md:text-5xl font-bold leading-tight">
          Unlimited movies, TV shows, and more
        </h1>
        <p className="mt-3 text-lg md:text-2xl text-[#e5e5e5]">Watch anywhere. Cancel anytime.</p>
        <div className="mt-6 flex flex-col sm:flex-row sm:items-center gap-3">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()}
            type="email"
            placeholder="Email address"
            className="w-full sm:w-auto sm:w-96 bg-[#303030]/70 border border-[#555] rounded px-4 py-3 text-white placeholder-[#8a8a8a] outline-none focus:border-white"
          />
          <button
            onClick={start}
            className="bg-[#e50914] hover:bg-[#c11119] text-white text-lg font-semibold rounded px-6 py-2.5 transition-colors"
          >
            Get Started
          </button>
        </div>
        {err && <p className="mt-2 text-sm text-[#e7b85a]">{err}</p>}
        <p className="mt-4 text-sm text-[#8a8a8a]">
          Ready to watch? Enter your email to create or restart your membership.
        </p>
      </div>
    </div>
  );
}
