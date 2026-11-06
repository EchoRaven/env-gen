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
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-[40px] w-[148px]" />
        <div className="flex items-center gap-6 text-[15px] text-white">
          <Link to="/register" className="hover:text-[#e5e5e5]">Join Now</Link>
          <Link to="/login" className="hover:text-[#e5e5e5]">Sign In</Link>
        </div>
      </header>

      <div className="relative z-10 flex flex-col items-center text-center px-6 pt-[28.8vh]">
        <h1 className="text-[46px] font-bold leading-[1.05] text-white">
          Unlimited movies, TV shows, and more
        </h1>
        <p className="mt-[3vh] text-[46px] font-bold leading-[1.05] text-white">
          Watch anywhere. Cancel anytime.
        </p>
        <p className="mt-[4.5vh] text-[15px] text-[#e5e5e5]">
          Ready to watch? Enter your email to create or restart your membership.
        </p>
        <div className="mt-[2.4vh] flex items-center gap-3 w-[min(634px,92vw)]">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()}
            type="email"
            placeholder="Email address"
            className="flex-1 h-[62px] bg-[#141414]/70 border border-[#3a3a3a] rounded px-4 text-[15px] text-white placeholder-[#8a8a8a] outline-none focus:border-[#8a8a8a]"
          />
          <button
            onClick={start}
            className="w-[236px] h-[62px] bg-[#e50914] hover:bg-[#c11119] text-white text-[22px] font-semibold rounded transition-colors"
          >
            Get Started
          </button>
        </div>
        {err && <p className="mt-2 text-sm text-[#e7b85a]">{err}</p>}
      </div>

      <footer className="absolute bottom-[6vh] left-0 right-0 z-10 px-[14.5vw] flex items-center gap-6">
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
