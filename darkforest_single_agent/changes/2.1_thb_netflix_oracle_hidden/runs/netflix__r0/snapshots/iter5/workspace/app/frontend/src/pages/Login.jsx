import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import AuthShell from './AuthShell';
import { API } from '../api';
import { useStore } from '../store';

export default function Login() {
  const { signIn } = useStore();
  const navigate = useNavigate();
  const loc = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [help, setHelp] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!email.trim() || !password) { setError('Please enter your email and password.'); return; }
    setBusy(true);
    try {
      const res = await API.login({ email: email.trim(), password });
      signIn(res.access_token);
      navigate('/profiles', { state: { from: loc.state?.from } });
    } catch (err) {
      setError(err.status === 401 ? 'Incorrect email or password. Please try again.' : err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell>
      <form className="auth-form" onSubmit={submit} noValidate>
        <h1>Enter your info to sign in</h1>
        <p className="auth-sub">Or <Link to="/signup">get started with a new account.</Link></p>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <label className="float-field">
          <span>Email or mobile number</span>
          <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} name="email" required />
        </label>
        <label className="float-field">
          <span>Password</span>
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} name="password" required />
        </label>
        <button className="btn-red block" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Continue'}</button>
        <button type="button" className="get-help" onClick={() => setHelp((h) => !h)} aria-expanded={help}>
          Get Help <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ transform: help ? 'rotate(180deg)' : 'none' }}><path d="m6 9 6 6 6-6" /></svg>
        </button>
        {help && (
          <div className="help-panel">
            <p>Try the demo account: <b>demo@netflix.local</b> / <b>netflix123</b></p>
            <p>New here? <Link to="/signup">Create an account</Link>.</p>
          </div>
        )}
        <p className="auth-fine">Passwords are verified server-side and stored as salted PBKDF2 hashes.</p>
      </form>
    </AuthShell>
  );
}
