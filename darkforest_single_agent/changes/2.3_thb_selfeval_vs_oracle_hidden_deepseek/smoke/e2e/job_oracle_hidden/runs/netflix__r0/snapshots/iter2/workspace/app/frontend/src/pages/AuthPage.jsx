import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useApp } from '../context'

export default function AuthPage({ mode = 'login' }) {
  const isLogin = mode === 'login'
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { login, register, token } = useApp()
  const [email, setEmail] = useState(params.get('email') || '')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  useEffect(() => {
    if (token) navigate('/profiles')
  }, [token, navigate])

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (isLogin) await login(email.trim(), password)
      else await register({ email: email.trim(), password, name: name.trim() })
      navigate('/profiles')
    } catch (err) {
      setError(err.message || 'Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }

  const useDemo = () => {
    setEmail('demo@netflix.com')
    setPassword('password123')
    setError('')
  }

  return (
    <div className="auth-page">
      <header className="auth-header">
        <Link to="/"><img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" /></Link>
      </header>
      <main className="auth-main">
        <form className="auth-card" onSubmit={submit}>
          <h1>{isLogin ? 'Enter your info to sign in' : 'Create your account'}</h1>
          <p className="auth-subhead">{isLogin ? <>Or <Link to="/signup">get started with a new account</Link>.</> : <>Already have an account? <Link to="/login">Sign in</Link>.</>}</p>
          {!isLogin && (
            <label className="auth-input">
              <input value={name} onChange={event => setName(event.target.value)} placeholder=" " autoComplete="name" required />
              <span>Your name</span>
            </label>
          )}
          <label className="auth-input">
            <input type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder=" " autoComplete="email" required />
            <span>Email or mobile number</span>
          </label>
          <label className="auth-input">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={event => setPassword(event.target.value)}
              placeholder=" "
              autoComplete={isLogin ? 'current-password' : 'new-password'}
              required
            />
            <span>Password</span>
            <button type="button" className="password-toggle" onClick={() => setShowPassword(value => !value)}>
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </label>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <button className="btn btn-red auth-submit" disabled={busy} type="submit">
            {busy ? 'Please wait…' : isLogin ? 'Sign In' : 'Create Account'}
          </button>
          <div className="auth-helper">
            <span>OR</span>
            <button type="button" className="auth-demo" onClick={useDemo}>Use demo account</button>
          </div>
          <p className="auth-fineprint">This page is protected by local authentication. Password checks use PBKDF2 and signed bearer tokens.</p>
        </form>
      </main>
      <footer className="auth-footer">
        <p>Questions? Sign in to open your account and profile controls.</p>
      </footer>
    </div>
  )
}
