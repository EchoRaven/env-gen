import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useApp } from '../state/AppContext'

export default function Login() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [mode, setMode] = useState(params.get('mode') === 'signup' ? 'signup' : 'signin')
  const [email, setEmail] = useState(params.get('email') || '')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { login, register } = useApp()

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    if (!email.includes('@')) { setError('Please enter a valid email address.'); return }
    if (password.length < 4) { setError('Password must be at least 4 characters.'); return }
    if (mode === 'signup' && password !== confirm) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      if (mode === 'signin') await login(email, password)
      else await register(email, password, name || email.split('@')[0])
      nav('/profiles')
    } catch (err) {
      const msg = err.message || 'Something went wrong'
      if (msg.includes('already registered') || msg.includes('Email already')) {
        setError('This email is already registered. Try signing in instead.')
      } else setError(msg)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <img className="wordmark" src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" />
        <h1>{mode === 'signin' ? 'Sign In' : 'Sign Up'}</h1>
        {error && <div className="error">{error}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </div>
          <div className="field">
            <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} />
          </div>
          {mode === 'signup' && (
            <>
              <div className="field">
                <input type="password" placeholder="Confirm password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
              </div>
              <div className="field">
                <input type="text" placeholder="Display name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
            </>
          )}
          <button className="btn-signin" type="submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'signin' ? 'Sign In' : 'Create Account'}
          </button>
        </form>
        <div className="alt">
          {mode === 'signin' ? (
            <>
              New to Netflix? <a onClick={() => { setMode('signup'); setError('') }}>Sign Up Now.</a>
            </>
          ) : (
            <>
              Already have an account? <a onClick={() => { setMode('signin'); setError('') }}>Sign In Now.</a>
            </>
          )}
        </div>
        <div className="note">This is a demo clone. Accounts are stored locally in the demo backend only.</div>
      </div>
    </div>
  )
}
