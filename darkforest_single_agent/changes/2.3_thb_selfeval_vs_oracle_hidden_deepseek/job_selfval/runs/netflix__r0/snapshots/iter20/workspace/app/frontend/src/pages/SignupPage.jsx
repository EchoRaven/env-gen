import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { BrandLogo } from '../components/Icon.jsx'
import { useAuth } from '../context/AuthContext.jsx'

export default function SignupPage() {
  const [params] = useSearchParams()
  const { register } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState(params.get('email') || '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    if (!name.trim()) return setError('Enter your name.')
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) return setError('Enter a valid email address.')
    if (password.length < 6) return setError('Your password must contain at least 6 characters.')
    setBusy(true)
    try {
      await register({ name: name.trim(), email: email.trim(), password })
      navigate('/profiles', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page signup-page">
      <div className="auth-background signup" />
      <div className="auth-shade" />
      <header className="auth-header"><Link to="/"><BrandLogo /></Link><Link to="/login" className="signin-link">Sign In</Link></header>
      <main className="auth-card-wrap">
        <form className="auth-card signup-card" onSubmit={submit}>
          <p className="auth-step">STEP <strong>1</strong> OF <strong>2</strong></p>
          <h1>Create a password to start your membership</h1>
          <p className="auth-lede">Just a few more steps and you're done! We hate paperwork, too.</p>
          {error && <div className="form-error" role="alert">{error}</div>}
          <label className="floating-field dark">
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder=" " autoComplete="name" />
            <span>Your name</span>
          </label>
          <label className="floating-field dark">
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder=" " autoComplete="email" />
            <span>Email address</span>
          </label>
          <label className="floating-field dark">
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder=" " autoComplete="new-password" />
            <span>Add a password</span>
          </label>
          <button type="submit" className="btn btn-red auth-submit" disabled={busy}>{busy ? 'Creating Account…' : 'Next'}</button>
          <p className="auth-switch">Already have an account? <Link to="/login">Sign in.</Link></p>
          <p className="auth-captcha">Your account and profiles are stored in the local application database.</p>
        </form>
      </main>
    </div>
  )
}
