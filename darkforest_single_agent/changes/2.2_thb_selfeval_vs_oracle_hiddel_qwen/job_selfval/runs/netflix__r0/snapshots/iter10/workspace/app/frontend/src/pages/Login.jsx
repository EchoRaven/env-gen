import { useRef, useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useApp } from "../store";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const { login } = useApp();
  const nav = useNavigate();
  const loc = useLocation();
  const pwdRef = useRef(null);

  const doLogin = async () => {
    setError("");
    setNote("");
    if (!/\S+@\S+\.\S+/.test(email)) {
      setError("Please enter a valid email address.");
      return;
    }
    if (!password) {
      setNote("Enter your password below to sign in.");
      pwdRef.current && pwdRef.current.focus();
      return;
    }
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
          <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-[38px] w-[163px]" />
        </Link>
      </div>

      <div className="w-[min(487px,92vw)] mx-auto pt-[10.4vh]">
        <h1 className="text-[34px] text-center text-[#e5e5e5]">Sign in to your account</h1>
        <p className="mt-[1.9vh] text-[13px] text-center text-[#7f7f7f]">
          Don&apos;t worry, we&apos;ll protect your privacy.
        </p>

        <form
          className="mt-[3.4vh] space-y-[1.1vh]"
          onSubmit={(e) => { e.preventDefault(); doLogin(); }}
        >
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full h-[63px] bg-[#332b2b]/40 border border-[#665656] rounded-[4px] px-3 text-[15px] text-white placeholder-[#9c8f8f] outline-none focus:border-white"
          />
          <button
            type="button"
            onClick={doLogin}
            className="w-full h-[55px] bg-[#e50914] hover:bg-[#f6121d] text-white text-[17px] font-semibold rounded-[4px] transition-colors"
          >
            Sign In
          </button>

          <div className="flex items-center gap-3 pt-[0.6vh] pb-[0.2vh]">
            <div className="h-px flex-1 bg-[#554545]" />
            <span className="text-[13px] text-[#9c8f8f]">or</span>
            <div className="h-px flex-1 bg-[#554545]" />
          </div>

          <input
            ref={pwdRef}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full h-[55px] bg-[#1f1718]/60 border border-[#5a4a4a] rounded-[4px] px-3 text-[15px] text-white placeholder-[#9c8f8f] outline-none focus:border-white"
          />
          <button
            type="submit"
            className="w-full h-[53px] bg-[#1f1718]/60 border border-[#8a7a7a] hover:bg-[#2c2122] text-white text-[15px] font-medium rounded-[4px] transition-colors"
          >
            Continue with password
          </button>

          {error && (
            <p className="text-[14px] text-[#e7b85a] bg-[#412c08]/40 border border-[#6a4b12] rounded px-3 py-2">
              {error}
            </p>
          )}
          {note && !error && (
            <p className="text-[13px] text-[#9c8f8f]">{note}</p>
          )}
          <div className="text-[14px] text-[#e5e5e5]">
            <button
              type="button"
              onClick={() => setNote("Password reset is disabled in this demo. Use the demo credentials: demo@netflix.local / demo1234")}
              className="hover:underline"
            >
              Forgot password?
            </button>
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
