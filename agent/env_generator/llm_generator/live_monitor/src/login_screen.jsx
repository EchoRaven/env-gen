window.LoginScreen = (function () {
  const { useState } = React;

  function LoginScreen({ onLoggedIn }) {
    const [username, setUsername] = useState("");
    const [token, setToken] = useState("");
    const [pending, setPending] = useState(false);
    const [error, setError] = useState("");

    async function submit(e) {
      e?.preventDefault?.();
      if (!username.trim() || !token.trim()) {
        setError("username and token required");
        return;
      }
      setPending(true);
      setError("");
      try {
        const r = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ username: username.trim(), token: token.trim() }),
        });
        if (!r.ok) {
          const data = await r.json().catch(() => ({}));
          setError(data.error || `HTTP ${r.status}`);
          setPending(false);
          return;
        }
        const data = await r.json();
        onLoggedIn?.(data.username);
      } catch (e) {
        setError(String(e));
        setPending(false);
      }
    }

    return (
      <div className="login-screen">
        <form className="login-card" onSubmit={submit}>
          <h1>env-gen Live Monitor</h1>
          <p className="login-hint">Sign in to manage projects, agents, and runs.</p>
          {error && <div className="login-error">{error}</div>}
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </label>
          <label>
            Access token
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} />
          </label>
          <button type="submit" disabled={pending}>
            {pending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  return LoginScreen;
})();
