import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { BrandLogo } from '../components/Icon.jsx'
import { useAuth } from '../context/AuthContext.jsx'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [step, setStep] = useState('email')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function continueWithEmail(event) {
    event.preventDefault()
    setError('')
    const value = email.trim()
    if (!value || !/^\S+@\S+\.\S+$/.test(value)) {
      setError('Please enter a valid email address.')
      return
    }
    setStep('password')
  }

  async function submit(event) {
    event.preventDefault()
    setError('')
    if (!password) {
      setError('Enter your password.')
      return
    }
    setBusy(true)
    try {
      await login(email.trim(), password)
      navigate(location.state?.from || '/profiles', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-glow" />
      <header className="login-header">
        <Link to="/"><BrandLogo /></Link>
        <p>New to Netflix? <Link to="/signup">Sign up now.</Link></p>
      </header>
      <main className="login-main">
        <div className="login-panel">
          <h1>{step === 'email' ? 'Enter your info to sign in' : 'Enter your password'}</h1>
          {step === 'email' ? (
            <p className="login-sub">Or get started with a new account.</p>
          ) : (
            <p className="login-sub login-email-line"><span>{email}</span><button type="button" onClick={() => { setStep('email'); setPassword(''); setError('') }}>Change</button></p>
          )}
          {error && <div className="form-error" role="alert">{error}</div>}
          {step === 'email' ? (
            <form onSubmit={continueWithEmail}>
              <label className="floating-field light">
                <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder=" " autoComplete="email" autoFocus />
                <span>Email or mobile number</span>
              </label>
              <button type="submit" className="btn btn-red login-submit">Continue</button>
            </form>
          ) : (
            <form onSubmit={submit}>
              <label className="floating-field light">
                <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder=" " autoComplete="current-password" autoFocus />
                <span>Password</span>
              </label>
              <button type="submit" className="btn btn-red login-submit" disabled={busy}>{busy ? 'Signing In…' : 'Sign In'}</button>
              <button type="button" className="login-back" onClick={() => { setStep('email'); setPassword(''); setError('') }}>Back</button>
            </form>
          )}
          <button type="button" className="login-help" onClick={() => navigate('/help')}>Get Help</button>
          <p className="login-captcha">This page is protected by a real password check. Demo access: demo@netflix.com / demo123.</p>
        </div>
      </main>
      <footer className="login-footer">
        <p>Questions? Visit the Help Center.</p>
        <div className="login-footer-links">
          <Link to="/help#faq">FAQ</Link>
          <Link to="/help">Help Center</Link>
          <Link to="/help#account">Account</Link>
          <Link to="/help#about">Media Center</Link>
          <Link to="/help#about">Investor Relations</Link>
          <Link to="/help#about">Jobs</Link>
          <Link to="/help#privacy">Privacy</Link>
          <Link to="/help#terms">Terms of Use</Link>
        </div>
        <span>Netflix clone · Built from the provided catalog dataset.</span>
      </footer>
    </div>
  )
}
