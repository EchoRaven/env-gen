import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useApp } from "../store";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const { login } = useApp();
  const nav = useNavigate();
  const loc = useLocation();

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    const r = await login(email, password);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    nav(loc.state?.from || "/profiles", { replace: true });
  };

  return (
    <div
      className="min-h-screen relative flex flex-col"
      style={{ background: "radial-gradient(120% 90% at 50% 0%, #2b0d10 0%, #1a0a0c 45%, #141414 80%)" }}
    >
      <div className="pt-[26px] px-[11vw]">
        <Link to="/" aria-label="Netflix home">
          <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-[38px]" />
        </Link>
      </div>

      <div className="w-[min(487px,92vw)] mx-auto pt-[9.5vh]">
        <h1 className="text-[40px] font-medium mb-[3.4vh]">Sign In</h1>
        <form onSubmit={submit} className="space-y-5">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full h-[52px] bg-[#e50914] border border-white rounded-[4px] px-2 text-white placeholder-[#ffb3b7] outline-none focus:border-white"
          />
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full h-[52px] bg-[#1f1f1f] border border-[#888] rounded-[4px] px-2 text-white placeholder-[#999] outline-none focus:border-white"
          />
          <button
            type="submit"
            className="w-full h-[52px] bg-[#e50914] hover:bg-[#f6121d] text-white text-[17px] font-semibold rounded-[4px] transition-colors"
          >
            Sign In
          </button>
          {error && (
            <p className="text-[14px] text-[#e7b85a] bg-[#412c08]/40 border border-[#6a4b12] rounded px-3 py-2">
              {error}
            </p>
          )}
          <div className="text-[14px] text-[#e5e5e5]">
            <Link to="/register" className="hover:underline">
              Forgot password?
            </Link>
          </div>
        </form>
        <div className="mt-[3vh] text-[15px]">
          <span className="text-[#e5e5e5]">New to Netflix? </span>
          <Link to="/register" className="text-white hover:underline">
            Sign up now.
          </Link>
        </div>
      </div>

      <div className="mt-auto pt-8 pb-4 px-[14.5vw] flex items-end justify-between text-[13px] text-[#606063]">
        <div className="space-y-2">
          <div>
            Don&apos;t have an account?{" "}
            <Link to="/register" className="text-[#e5e5e5] hover:underline">
              Sign Up
            </Link>
          </div>
          <div>
            Used to have Netflix?{" "}
            <Link to="/login" className="text-[#e5e5e5] hover:underline">
              Sign in here
            </Link>
          </div>
        </div>
        <div className="text-white bg-black/40 border border-[#4d4d4d] rounded px-3 py-1.5">
          English ▾
        </div>
      </div>
    </div>
  );
}
