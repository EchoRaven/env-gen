import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from '../components/Icon'
import Logo from '../components/Logo'
import { useAuth } from '../context/AuthContext'

const COLLAGE = [
  'movie_1275779', 'tv_66732', 'movie_1368337', 'tv_94997', 'movie_1083381', 'tv_37854',
  'movie_1368314', 'tv_60625', 'movie_931285', 'tv_2912', 'movie_1668364', 'tv_2261',
  'movie_1400837', 'tv_241882', 'movie_1523145', 'tv_2734', 'movie_1318621', 'tv_124364',
].map((name) => `/assets/posters/${name}.jpg`)

export default function LandingPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const { isAuthenticated } = useAuth()

  const getStarted = (event) => {
    event.preventDefault()
    const clean = email.trim()
    if (!clean || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean)) {
      setError('Please enter a valid email address.')
      return
    }
    navigate(`/login?email=${encodeURIComponent(clean)}&mode=signup`)
  }

  return (
    <div className="landing">
      <div className="landing-collage" aria-hidden="true">
        {COLLAGE.map((src, index) => (
          <div className="collage-tile" key={src} style={{ animationDelay: `${(index % 6) * -1.7}s` }}>
            <img src={src} alt="" />
          </div>
        ))}
      </div>
      <div className="landing-shade" />
      <header className="landing-header">
        <Logo width={150} />
        <div className="landing-header-actions">
          {isAuthenticated ? (
            <button className="btn btn-red btn-small" onClick={() => navigate('/browse')}>Browse</button>
          ) : (
            <button className="btn btn-red btn-small" onClick={() => navigate('/login')}>Sign In</button>
          )}
        </div>
      </header>
      <main className="landing-main">
        <div className="landing-copy">
          <p className="landing-kicker">The streaming service you know, rebuilt end to end.</p>
          <h1>Unlimited movies, TV shows, and more</h1>
          <p className="landing-subtitle">Starts at $0. Cancel anytime.</p>
          <p className="landing-ready">Ready to watch? Enter your email to create or restart your membership.</p>
          <form className="landing-form" onSubmit={getStarted} noValidate>
            <label className={`landing-email ${email ? 'filled' : ''}`}>
              <input
                type="email"
                value={email}
                onChange={(event) => { setEmail(event.target.value); setError('') }}
                placeholder=" "
                aria-label="Email address"
              />
              <span>Email address</span>
            </label>
            <button className="btn btn-red landing-submit" type="submit">
              Get Started <Icon name="chevronRight" size={24} />
            </button>
          </form>
          {error ? <p className="form-error landing-error">{error}</p> : null}
          <p className="landing-demo">Demo access: <strong>demo@netflix.com</strong> · <strong>demo123</strong></p>
        </div>
      </main>
      <div className="landing-curve" />
      <footer className="landing-footer">
        <span>Netflix clone catalog experience</span>
        <span>Real titles · Real trailers · Per-profile recommendations</span>
      </footer>
    </div>
  )
}
