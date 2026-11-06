import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

const POSTERS = [
  "/assets/posters/tv_37854.jpg",
  "/assets/posters/movie_1003596.jpg",
  "/assets/posters/tv_279323.jpg",
  "/assets/posters/movie_1339713.jpg",
  "/assets/posters/tv_12415.jpg",
  "/assets/posters/movie_1108427.jpg",
  "/assets/posters/movie_1275779.jpg",
  "/assets/posters/movie_1081003.jpg"
];

export default function Landing() {
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const nav = useNavigate();

  const start = () => {
    if (!/\S+@\S+\.\S+/.test(email)) {
      setErr("Please enter a valid email address.");
      return;
    }
    setErr("");
    nav(`/register?email=${encodeURIComponent(email)}`);
  };

  return (
    <div className="relative min-h-screen bg-nfg overflow-hidden">
      {/* poster collage band */}
      <div className="absolute top-0 left-0 right-0 h-[42vh] flex">
        {POSTERS.map((p, i) => (
          <div key={i} className="flex-1 h-full">
            <img src={p} alt="" className="w-full h-full object-cover" />
          </div>
        ))}
      </div>
      <div className="absolute top-0 left-0 right-0 h-[42vh] bg-gradient-to-b from-black/30 via-black/30 to-[#141414]" />

      <header className="relative z-10 flex items-center justify-between px-[3.5vw] h-[84px]">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-[22px]" />
        <Link
          to="/login"
          className="bg-white text-black text-[15px] font-semibold rounded px-4 py-2 hover:bg-white/80"
        >
          Sign In
        </Link>
      </header>

      <div className="relative z-10 flex flex-col items-center text-center px-6 pt-[21vh]">
        <h1 className="text-[40px] md:text-[46px] font-bold leading-[1.15] text-white">
          Unlimited movies, TV shows, and more
        </h1>
        <p className="mt-2 text-[40px] md:text-[46px] font-bold leading-[1.15] text-white">
          Watch anywhere. Cancel anytime.
        </p>
        <p className="mt-[3.2vh] text-[15px] text-[#e5e5e5]">
          Ready to watch? Enter your email to create or restart your membership.
        </p>
        <div className="mt-[2vh] flex items-center gap-3 w-full max-w-[860px]">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()}
            type="email"
            placeholder="Email address"
            className="flex-1 bg-[#303030]/80 border border-[#555] rounded px-4 py-3.5 text-white placeholder-[#8a8a8a] outline-none focus:border-white"
          />
          <button
            onClick={start}
            className="bg-[#e50914] hover:bg-[#c11119] text-white text-[22px] font-semibold rounded px-8 py-2.5 transition-colors"
          >
            Get Started
          </button>
        </div>
        {err && <p className="mt-2 text-sm text-[#e7b85a]">{err}</p>}
      </div>

      <footer className="absolute bottom-[4vh] left-0 right-0 z-10 px-[14.5vw] flex items-center gap-6">
        <img
          src="/assets/brand/netflix_wordmark.svg"
          alt="NETFLIX"
          className="h-[18px]"
          style={{ filter: "invert(1)" }}
        />
        <span className="text-[12px] text-[#707070]">
          Netflix Clone — a streaming catalog demo built with real titles and trailers.
        </span>
        <span className="ml-auto text-[13px] text-white bg-black/50 border border-[#4d4d4d] rounded px-3 py-1.5">
          English ▾
        </span>
      </footer>
    </div>
  );
}
