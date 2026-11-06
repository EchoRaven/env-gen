import { useRef, useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useApp } from "../store";

const FOOTER_LINKS = [
  ["FAQ", "Help Center", "Netflix House", "Netflix Shop"],
  ["Terms of Use", "Privacy", "Cookie Preferences", "Corporate Information"]
];

export default function Login() {
  const [stage, setStage] = useState(1);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const { login } = useApp();
  const nav = useNavigate();
  const loc = useLocation();
  const pwdRef = useRef(null);

  const doContinue = () => {
    setError("");
    setNote("");
    if (!/\S+@\S+\.\S+/.test(email)) {
      setError("Please enter a valid email address.");
      return;
    }
    setStage(2);
    setTimeout(() => pwdRef.current && pwdRef.current.focus(), 50);
  };

  const doLogin = async () => {
    setError("");
    setNote("");
    if (!password) {
      setNote("Enter your password to sign in.");
      pwdRef.current && pwdRef.current.focus();
      return;
    }
    const r = await login(email, password);
    if (!r.ok) {
      setError("Incorrect email and password combination.");
      setNote("Demo credentials: demo@netflix.local / demo1234");
      return;
    }
    nav(loc.state?.from || "/profiles", { replace: true });
  };

  return (
    <div
      className="min-h-screen relative flex flex-col"
      style={{ background: "radial-gradient(130% 110% at 50% -10%, #4a1618 0%, #2a0f10 45%, #161616 85%)" }}
    >
      <div className="pt-[24px] px-[10.8vw]">
        <Link to="/" aria-label="Netflix home">
          <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="h-[38px] w-[163px]" />
        </Link>
      </div>

      <div className="w-[min(487px,92vw)] mx-auto pt-[10vh]">
        {stage === 1 ? (
          <>
            <h1 className="text-[34px] text-center text-white">Enter your info to sign in</h1>
            <p className="mt-[2.4vh] text-[15px] text-center text-[#7f7f7f]">
              Or{" "}
              <Link to="/register" className="text-white hover:underline">
                get started with a new account.
              </Link>
            </p>
            <form
              className="mt-[2.9vh]"
              onSubmit={(e) => { e.preventDefault(); doContinue(); }}
            >
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email or mobile number"
                className="w-full h-[55px] bg-[#1b1213]/70 border border-[#4e3d3d] rounded-[3px] px-3.5 text-[15px] text-white placeholder-[#8f8383] outline-none focus:border-[#9a8b8b]"
              />
              {error && (
                <p className="mt-2 text-[14px] text-[#e5e5e5] bg-[#412c08]/40 border border-[#6a4b12] rounded px-3 py-2">
                  {error}
                </p>
              )}
              <button
                type="submit"
                className="mt-[2.2vh] w-full h-[44px] bg-[#e50914] hover:bg-[#c21119] text-white text-[15px] font-medium rounded-[3px] transition-colors"
              >
                Continue
              </button>
            </form>
            <button
              onClick={() => setNote("Password reset is disabled in this demo. Use demo@netflix.local / demo1234.")}
              className="mt-[5.2vh] text-[15px] text-white hover:underline"
            >
              Get Help
            </button>
          </>
        ) : (
          <>
            <h1 className="text-[34px] text-center text-white">Sign in</h1>
            <form
              className="mt-[4vh]"
              onSubmit={(e) => { e.preventDefault(); doLogin(); }}
            >
              <input
                ref={pwdRef}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                className="w-full h-[55px] bg-[#1b1213]/70 border border-[#4e3d3d] rounded-[3px] px-3.5 text-[15px] text-white placeholder-[#8f8383] outline-none focus:border-[#9a8b8b]"
              />
              {error && (
                <p className="mt-2 text-[14px] text-[#e5e5e5] bg-[#412c08]/40 border border-[#6a4b12] rounded px-3 py-2">
                  {error}
                </p>
              )}
              {note && <p className="mt-2 text-[13px] text-[#8f8383]">{note}</p>}
              <button
                type="submit"
                className="mt-[2.2vh] w-full h-[44px] bg-[#e50914] hover:bg-[#c21119] text-white text-[15px] font-medium rounded-[3px] transition-colors"
              >
                Sign in
              </button>
            </form>
            <button
              onClick={() => { setStage(1); setError(""); setNote(""); }}
              className="mt-[2.4vh] flex items-center gap-2 text-[15px] text-white hover:underline"
            >
              <span aria-hidden="true">←</span> Go back
            </button>
          </>
        )}
      </div>

      <p className="w-[min(487px,92vw)] mx-auto mt-[2.6vh] text-[13px] text-[#7f7f7f]">
        This page is protected by Google reCAPTCHA to ensure you&apos;re not a bot.
      </p>

      <div className="mt-auto pt-[3vh] pb-[2.6vh] px-[10.9vw]">
        <p className="text-[15px] text-[#e5e5e5]">
          Questions? Call 1-844-569-7700 (Toll-Free)
        </p>
        <div className="mt-[2.2vh] grid grid-cols-4">
          {FOOTER_LINKS[0].map((l) => (
            <Link key={l} to="/login" className="text-[15px] text-[#bdbdbd] hover:text-white">
              {l}
            </Link>
          ))}
        </div>
        <div className="mt-[1.4vh] grid grid-cols-4">
          {FOOTER_LINKS[1].map((l) => (
            <Link key={l} to="/login" className="text-[15px] text-[#bdbdbd] hover:text-white">
              {l}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
