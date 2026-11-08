import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { Wordmark } from '../icons'

export default function Signup() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [name, setName] = useState('')
  const [email, setEmail] = useState(new URLSearchParams(location.search).get('email') || '')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    if (!name.trim()) return setError('Enter your name.')
    if (!email.includes('@')) return setError('Enter a valid email address.')
    if (password.length < 6) return setError('Your password must contain at least 6 characters.')
    if (password !== confirm) return setError('Passwords do not match.')
    setBusy(true)
    try {
      await register(email.trim(), password, name.trim())
      navigate('/profiles')
    } catch (requestError) {
      setError(requestError.message || 'Could not create your account.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page signup-page">
      <div className="auth-background" aria-hidden="true">
        <img src="/assets/backdrops/tv_66732.jpg" alt="" />
        <img src="/assets/backdrops/movie_1368337.jpg" alt="" />
        <img src="/assets/backdrops/tv_124364.jpg" alt="" />
        <div className="auth-shade" />
      </div>
      <header className="auth-header">
        <Link to="/" aria-label="Netflix home">
          <Wordmark height={38} />
        </Link>
        <Link className="sign-in-button" to="/login">Sign In</Link>
      </header>
      <main className="auth-main">
        <section className="auth-card signup-card" aria-labelledby="signup-heading">
          <h1 id="signup-heading">Create your account</h1>
          <p className="signup-subtitle">Unlimited movies, TV shows and more. Cancel anytime.</p>
          {error ? <div className="auth-error" role="alert">{error}</div> : null}
          <form onSubmit={submit}>
            <label className={`floating-field auth-field ${name ? 'filled' : ''}`}>
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder=" " autoComplete="name" />
              <span>Your name</span>
            </label>
            <label className={`floating-field auth-field ${email ? 'filled' : ''}`}>
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder=" " autoComplete="email" />
              <span>Email address</span>
            </label>
            <label className={`floating-field auth-field ${password ? 'filled' : ''}`}>
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder=" " autoComplete="new-password" />
              <span>Add a password</span>
            </label>
            <label className={`floating-field auth-field ${confirm ? 'filled' : ''}`}>
              <input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} placeholder=" " autoComplete="new-password" />
              <span>Confirm password</span>
            </label>
            <button className="auth-submit" type="submit" disabled={busy}>
              {busy ? 'Creating account…' : 'Get Started'}
            </button>
          </form>
          <p className="signup-legal">
            Your account will include a profile so you can start watching immediately. Change profiles anytime.
          </p>
          <p className="auth-switch">
            Already have an account? <Link to="/login">Sign in</Link>.
          </p>
        </section>
      </main>
    </div>
  )
}
