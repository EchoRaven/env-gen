import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { Wordmark } from '../icons'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [step, setStep] = useState('email')
  const [email, setEmail] = useState(new URLSearchParams(location.search).get('email') || '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [helpOpen, setHelpOpen] = useState(new URLSearchParams(location.search).get('help') === '1')

  const continueWithEmail = (event) => {
    event.preventDefault()
    setError('')
    const value = email.trim()
    if (!value || !value.includes('@')) {
      setError('Please enter a valid email or mobile number.')
      return
    }
    setStep('password')
  }

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    if (!password) {
      setError('Please enter your password.')
      return
    }
    setBusy(true)
    try {
      await login(email.trim(), password)
      navigate('/profiles')
    } catch (requestError) {
      setError(requestError.message || 'Sign in failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const demoLogin = async () => {
    setBusy(true)
    setError('')
    try {
      await login('demo@netflix.com', 'password123')
      navigate('/profiles')
    } catch (requestError) {
      setError(requestError.message || 'The demo account is unavailable.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="signin-page">
      <header className="signin-header">
        <Link to="/" aria-label="Netflix home">
          <Wordmark height={36} />
        </Link>
      </header>
      <main className="signin-main">
        <section className="signin-panel">
          <h1>{step === 'email' ? 'Enter your info to sign in' : 'Enter your password'}</h1>
          <p className="signin-subtitle">
            {step === 'email' ? (
              <>Or <Link to="/signup">get started with a new account</Link>.</>
            ) : (
              <>Signing in as <strong>{email}</strong>. <button type="button" onClick={() => setStep('email')}>Change</button></>
            )}
          </p>
          {error ? <div className="signin-error" role="alert">{error}</div> : null}
          {step === 'email' ? (
            <form onSubmit={continueWithEmail}>
              <label className={`signin-field ${email ? 'filled' : ''}`}>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => { setEmail(event.target.value); setError('') }}
                  placeholder=" "
                  autoComplete="email"
                  autoFocus
                />
                <span>Email or mobile number</span>
              </label>
              <button className="signin-continue" type="submit">Continue</button>
            </form>
          ) : (
            <form onSubmit={submit}>
              <label className={`signin-field ${password ? 'filled' : ''}`}>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => { setPassword(event.target.value); setError('') }}
                  placeholder=" "
                  autoComplete="current-password"
                  autoFocus
                />
                <span>Password</span>
              </label>
              <button className="signin-continue" type="submit" disabled={busy}>
                {busy ? 'Signing In…' : 'Sign In'}
              </button>
            </form>
          )}
          <button className="signin-get-help" type="button" onClick={() => setHelpOpen((value) => !value)}>
            Get Help
          </button>
          {helpOpen ? (
            <div className="signin-help-panel">
              <p>Use the demo account below, or create a new Netflix account.</p>
              <p className="demo-credentials">demo@netflix.com · password123</p>
              <button type="button" onClick={demoLogin} disabled={busy}>Sign in with the demo account</button>
            </div>
          ) : null}
          <p className="signin-captcha">This page is protected by Google reCAPTCHA to ensure you're not a bot.</p>
        </section>
      </main>
      <footer className="signin-footer">
        <p>Questions? Call 1-844-569-7700 (Toll-Free)</p>
        <div>
          <Link to="/">FAQ</Link>
          <Link to="/login?help=1">Help Centre</Link>
          <Link to="/browse">Netflix House</Link>
          <Link to="/signup">Netflix Shop</Link>
          <Link to="/login">Terms of Use</Link>
          <Link to="/login">Privacy</Link>
          <Link to="/login">Cookie Preferences</Link>
          <Link to="/signup">Corporate Information</Link>
        </div>
      </footer>
    </div>
  )
}
