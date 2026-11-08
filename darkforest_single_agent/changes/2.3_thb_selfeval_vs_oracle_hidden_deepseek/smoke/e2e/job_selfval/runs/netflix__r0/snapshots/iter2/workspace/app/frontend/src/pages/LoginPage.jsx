import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api'
import Logo from '../components/Logo'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const [params] = useSearchParams()
  const [mode, setMode] = useState(params.get('mode') === 'signup' ? 'signup' : 'signin')
  const [name, setName] = useState('')
  const [email, setEmail] = useState(params.get('email') || '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { signIn, token, loading } = useAuth()

  useEffect(() => {
    if (!loading && token) navigate('/profiles', { replace: true })
  }, [loading, token, navigate])

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    if (!email.trim() || !password) {
      setError('Enter your email and password.')
      return
    }
    if (mode === 'signup' && password.length < 6) {
      setError('Your password must contain at least 6 characters.')
      return
    }
    setSubmitting(true)
    try {
      const path = mode === 'signup' ? '/auth/register' : '/auth/login'
      const body = mode === 'signup'
        ? { email: email.trim(), password, name: name.trim() || undefined }
        : { email: email.trim(), password }
      const data = await api.post(path, body)
      signIn(data)
      const next = location.state?.from
      navigate(next || '/profiles', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const useDemo = () => {
    setMode('signin')
    setEmail('demo@netflix.com')
    setPassword('demo123')
    setError('')
  }

  return (
    <div className="auth-page">
      <div className="auth-bg" aria-hidden="true">
        {['tv_66732', 'movie_1368337', 'tv_37854', 'movie_1275779', 'tv_94997', 'movie_1083381'].map((name) => (
          <img key={name} src={`/assets/backdrops/${name}.jpg`} alt="" />
        ))}
      </div>
      <div className="auth-shade" />
      <header className="auth-header"><Logo width={148} /></header>
      <main className="auth-main">
        <section className="auth-card">
          <h1>{mode === 'signin' ? 'Sign In' : 'Create your account'}</h1>
          <p className="auth-lead">{mode === 'signin' ? 'Watch on any screen. Your profiles, My List, and ratings stay in sync.' : 'One account. Up to five profiles. Your own list and ratings.'}</p>
          <form onSubmit={submit} className="auth-form">
            {mode === 'signup' ? (
              <label className="field">
                <span>Name</span>
                <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Your name" autoComplete="name" />
              </label>
            ) : null}
            <label className="field">
              <span>Email or mobile number</span>
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email address" autoComplete="email" required />
            </label>
            <label className="field">
              <span>Password</span>
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} required />
            </label>
            {error ? <p className="form-error">{error}</p> : null}
            <button className="btn btn-red auth-submit" type="submit" disabled={submitting}>
              {submitting ? 'Please wait…' : mode === 'signin' ? 'Sign In' : 'Sign Up'}
            </button>
          </form>
          <div className="auth-switch">
            <span>{mode === 'signin' ? 'New to Netflix?' : 'Already have an account?'}</span>
            <button type="button" onClick={() => { setMode(mode === 'signin' ? 'signup' : 'signin'); setError('') }}>
              {mode === 'signin' ? 'Sign up now.' : 'Sign in now.'}
            </button>
          </div>
          <button type="button" className="demo-login" onClick={useDemo}>
            <span>Try the demo profile</span>
            <small>demo@netflix.com · demo123</small>
          </button>
          <p className="auth-legal">This page is protected by a real account system. Passwords are checked and sessions use bearer tokens.</p>
        </section>
      </main>
      <footer className="auth-footer">
        <span>Questions? Browse the catalog after signing in.</span>
        <Link to="/">Return to home</Link>
      </footer>
    </div>
  )
}
