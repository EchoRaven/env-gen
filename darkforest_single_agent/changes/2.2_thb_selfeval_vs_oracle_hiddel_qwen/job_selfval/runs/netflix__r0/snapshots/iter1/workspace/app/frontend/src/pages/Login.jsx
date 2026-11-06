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
    <div className="min-h-screen relative" style={{ background: "radial-gradient(120% 100% at 50% 0%, #2a0608 0%, #1b0a0c 40%, #141414 75%)" }}>
      <div className="h-[120px] border-b border-[#262626] flex items-center px-6 md:px-[4vw]">
        <Link to="/">
          <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-6 md:h-8" />
        </Link>
      </div>
      <div className="w-[408px] max-w-[92vw] mx-auto pt-[7vh]">
        <h1 className="text-[32px] mb-6">Sign In</h1>
        <form onSubmit={submit} className=" space-y-4">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full bg-[#303030] border border-[#555] rounded px-4 py-3 outline-none focus:border-[#8a8a8a]"
          />
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full bg-[#303030] border border-[#555] rounded px-4 py-3 outline-none focus:border-[#8a8a8a]"
          />
          <div>
            <button
              type="submit"
              className="w-full bg-[#e50914] hover:bg-[#c11119] text-white font-semibold py-3 rounded transition-colors"
            >
              Sign In
            </button>
          </div>
          {error && (
            <p className="text-sm text-[#e7b85a] bg-[#412c08]/40 border border-[#6a4b12] rounded px-3 py-2">
              {error}
            </p>
          )}
          <div className="text-[#707070] text-sm">or</div>
          <div className="text-sm text-[#707070]">
            New to Netflix?{" "}
            <Link to="/register" className="text-white hover:underline">
              Sign up now.
            </Link>
          </div>
          <div className="text-xs text-[#707070]">
            By continuing, you confirm that you have read and agree to our Terms of Use and our
            Privacy Notice.
          </div>
        </form>
      </div>
    </div>
  );
}
