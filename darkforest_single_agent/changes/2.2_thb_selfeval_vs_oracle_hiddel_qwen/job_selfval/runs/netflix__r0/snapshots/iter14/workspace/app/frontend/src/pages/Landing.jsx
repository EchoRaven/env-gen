import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

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
      {/* dark moody background (subtle warm→purple tint, like the reference) */}
      <div className="absolute inset-0 bg-gradient-to-b from-[#2a241d] via-[#161219] to-[#1a1327]" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(255,255,255,0.05),transparent_55%)]" />

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
