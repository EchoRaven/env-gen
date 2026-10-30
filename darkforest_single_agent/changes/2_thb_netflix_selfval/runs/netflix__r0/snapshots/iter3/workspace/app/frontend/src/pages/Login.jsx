import { useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useSession } from '../session.jsx'

export default function Login({ signup = false }) {
  const { token, signIn } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [email, setEmail] = useState(params.get('email') || '')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (token) return <Navigate to="/profiles" replace />

  const submit = async (e) => {
    e.preventDefault()
    setError(''); setBusy(true)
    try {
      const data = signup
        ? await api.register({ email: email.trim(), password, name: name.trim() || undefined })
        : await api.login({ email: email.trim(), password })
      signIn(data)
      navigate('/profiles')
    } catch (err) {
      setError(err.status === 401 ? 'Incorrect email or password. Please try again.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <header className="auth-header">
        <Link to="/" aria-label="Netflix"><img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="auth-logo" /></Link>
      </header>
      <main className="auth-main">
        <form className="auth-form" onSubmit={submit}>
          <h1>{signup ? 'Create your account' : 'Enter your info to sign in'}</h1>
          <p className="auth-sub">
            {signup ? 'Just a few more steps and you’re done.' : 'Or get started with a new account.'}
          </p>
          {error && <div className="auth-error" role="alert">{error}</div>}
          {signup && (
            <label className="float-field">
              <span>Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </label>
          )}
          <label className="float-field">
            <span>Email address</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </label>
          <label className="float-field">
            <span>Password</span>
            <input type="password" required minLength={signup ? 6 : 1} value={password}
              onChange={(e) => setPassword(e.target.value)} autoComplete={signup ? 'new-password' : 'current-password'} />
          </label>
          <button type="submit" className="btn-red block" disabled={busy}>
            {busy ? 'Please wait…' : signup ? 'Create Account' : 'Sign In'}
          </button>
          <p className="auth-switch">
            {signup
              ? <>Already have an account? <Link to="/login">Sign in now.</Link></>
              : <>New to Netflix? <Link to="/signup">Sign up now.</Link></>}
          </p>
          {!signup && <p className="auth-demo">Demo account: <b>demo@netflix.local</b> / <b>netflix123</b></p>}
        </form>
      </main>
      <footer className="auth-footer">
        <p>Questions? This is a local Netflix clone — your data stays in this environment.</p>
      </footer>
    </div>
  )
}
