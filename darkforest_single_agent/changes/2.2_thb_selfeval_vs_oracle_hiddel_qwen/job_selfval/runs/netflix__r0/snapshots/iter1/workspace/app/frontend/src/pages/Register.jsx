import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useApp } from "../store";

export default function Register() {
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") || "");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const { register } = useApp();
  const nav = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    const r = await register(email, password, email.split("@")[0]);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    nav("/profiles", { replace: true });
  };

  return (
    <div className="min-h-screen relative" style={{ background: "radial-gradient(120% 100% at 50% 0%, #2a0608 0%, #1b0a0c 40%, #141414 75%)" }}>
      <div className="h-[120px] border-b border-[#262626] flex items-center px-6 md:px-[4vw]">
        <Link to="/">
          <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-6 md:h-8" />
        </Link>
      </div>
      <div className="w-[408px] max-w-[92vw] mx-auto pt-[7vh]">
        <h1 className="text-[32px] mb-6">Sign Up</h1>
        <form onSubmit={submit} className="space-y-4">
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
            placeholder="Password (min. 6 characters)"
            className="w-full bg-[#303030] border border-[#555] rounded px-4 py-3 outline-none focus:border-[#8a8a8a]"
          />
          <input
            type="password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Confirm password"
            className="w-full bg-[#303030] border border-[#555] rounded px-4 py-3 outline-none focus:border-[#8a8a8a]"
          />
          <button
            type="submit"
            className="w-full bg-[#e50914] hover:bg-[#c11119] text-white font-semibold py-3 rounded transition-colors"
          >
            Get Started
          </button>
          {error && (
            <p className="text-sm text-[#e7b85a] bg-[#412c08]/40 border border-[#6a4b12] rounded px-3 py-2">
              {error}
            </p>
          )}
          <div className="text-sm text-[#707070]">
            Already have an account?{" "}
            <Link to="/login" className="text-white hover:underline">
              Sign in
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
