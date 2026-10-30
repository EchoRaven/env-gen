import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import AuthShell from './AuthShell';
import { API } from '../api';
import { useStore } from '../store';

export default function Signup() {
  const { signIn } = useStore();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get('email') || '');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) { setError('Please enter a valid email address.'); return; }
    if (password.length < 6) { setError('Your password must contain at least 6 characters.'); return; }
    setBusy(true);
    try {
      const res = await API.register({ email: email.trim(), password, name: name.trim() || undefined });
      signIn(res.access_token);
      navigate('/profiles');
    } catch (err) {
      setError(err.status === 409 ? 'An account with this email already exists. Sign in instead.' : err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell>
      <form className="auth-form" onSubmit={submit} noValidate>
        <h1>Create a password to start your membership</h1>
        <p className="auth-sub">Just a few more steps and you’re done! Already have an account? <Link to="/login">Sign in.</Link></p>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <label className="float-field">
          <span>Email</span>
          <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} name="email" required />
        </label>
        <label className="float-field">
          <span>Name (optional)</span>
          <input type="text" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} name="name" maxLength={60} />
        </label>
        <label className="float-field">
          <span>Add a password</span>
          <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} name="password" required />
        </label>
        <button className="btn-red block" type="submit" disabled={busy}>{busy ? 'Creating account…' : 'Sign Up'}</button>
      </form>
    </AuthShell>
  );
}
