import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

const COLLAGE = [
  "movie_1003596.jpg", "movie_1083381.jpg", "movie_1108427.jpg", "movie_1212763.jpg",
  "movie_1273221.jpg", "movie_1280738.jpg", "movie_1314481.jpg", "movie_1318621.jpg",
  "movie_1368314.jpg", "movie_1400837.jpg", "movie_1468683.jpg", "movie_1668364.jpg",
  "movie_687163.jpg", "movie_936075.jpg", "tv_12415.jpg", "tv_125988.jpg",
  "tv_15226.jpg", "tv_206559.jpg", "tv_2224.jpg", "tv_237020.jpg",
  "tv_254528.jpg", "tv_27181.jpg", "tv_277439.jpg", "tv_279323.jpg",
  "tv_289139.jpg", "tv_296206.jpg", "tv_321564.jpg", "tv_498.jpg", "tv_63770.jpg"
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
    <div className="relative min-h-screen overflow-hidden">
      {/* full-bleed poster collage of the real catalog (darkened) */}
      <div className="absolute inset-0 grid grid-cols-5 md:grid-cols-10 grid-rows-3 bg-[#0c0a10]">
        {COLLAGE.map((p, i) => (
          <div key={p} className="overflow-hidden" style={{ transform: `rotate(${(i % 3) - 1}deg) scale(1.12)` }}>
            <img
              src={`/assets/posters/${p}`}
              alt=""
              loading="lazy"
              className="w-full h-full object-cover opacity-50"
            />
          </div>
        ))}
      </div>
      <div className="absolute inset-0 bg-gradient-to-b from-[#141414]/85 via-[#151019]/70 to-[#141414]/92" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,0,0,0.55),transparent_70%)]" />

      <header className="relative z-10 flex items-center justify-between px-[8.6vw] h-[84px]">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-[34px] w-[127px]" />
        <div className="flex items-center gap-6">
          <Link to="/register" className="text-[15px] text-white/90 hover:text-white">Join Now</Link>
          <Link
            to="/login"
            className="text-[15px] font-semibold text-white bg-[#e50914] hover:bg-[#c11119] rounded px-[22px] py-[9px] transition-colors"
          >
            Sign In
          </Link>
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

      <div
        className="absolute left-1/2 top-[80.4vh] z-10 h-[4px] w-[46.8vw] -translate-x-1/2 rounded-full bg-[#e50914]/70 blur-[1.5px]"
      />

      <footer className="absolute bottom-[5.4vh] left-[9.4vw] right-[10.5vw] z-10 flex items-center">
        <svg viewBox="0 0 72 73" className="h-[72px] w-[72px] shrink-0" aria-hidden="true">
          <rect x="6" y="4" width="60" height="46" rx="9" fill="#ce652f" />
          <polygon points="34,16 34,38 52,27" fill="#1a1327" />
          <rect x="0" y="56" width="72" height="17" rx="4" fill="#ce652f" />
        </svg>
        <div className="ml-[30px]">
          <h2 className="text-[22px] font-semibold leading-tight text-white">
            The Netflix you love for just $8.99.
          </h2>
          <p className="mt-[6px] text-[15px] text-white/90">
            Get our most affordable, ad-supported plan.
          </p>
        </div>
        <Link
          to="/register"
          className="ml-auto text-[15px] font-semibold tracking-[0.08em] text-white hover:text-white/80"
        >
          Learn More
        </Link>
      </footer>
    </div>
  );
}
