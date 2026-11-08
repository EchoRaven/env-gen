import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AssetIcon, Wordmark } from '../icons'

const COLLAGE = [
  '/assets/backdrops/tv_94997.jpg',
  '/assets/backdrops/movie_1081003.jpg',
  '/assets/backdrops/tv_66732.jpg',
  '/assets/posters/movie_1368337.jpg',
  '/assets/backdrops/tv_37854.jpg',
  '/assets/posters/tv_94997.jpg',
  '/assets/backdrops/movie_969681.jpg',
  '/assets/posters/movie_1275779.jpg',
  '/assets/backdrops/tv_124364.jpg',
  '/assets/posters/tv_66732.jpg',
  '/assets/backdrops/movie_1315772.jpg',
  '/assets/posters/movie_1081003.jpg',
]

export default function Landing() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [language, setLanguage] = useState('en')
  const spanish = language === 'es'

  const start = (event) => {
    event.preventDefault()
    const value = email.trim()
    if (!value || !value.includes('@')) {
      setError('Please enter a valid email address.')
      return
    }
    navigate(`/signup?email=${encodeURIComponent(value)}`)
  }

  return (
    <div className="landing-page">
      <div className="landing-collage" aria-hidden="true">
        {COLLAGE.map((src, index) => (
          <div className={`collage-tile collage-tile-${index + 1}`} key={src}>
            <img src={src} alt="" />
          </div>
        ))}
        <div className="collage-fade" />
      </div>
      <header className="landing-header">
        <Link to="/" aria-label="Netflix">
          <Wordmark height={40} />
        </Link>
        <div className="landing-header-actions">
          <select className="language-select" aria-label="Language" value={language} onChange={(event) => setLanguage(event.target.value)}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </select>
          <Link className="sign-in-button" to="/login">
            {spanish ? 'Iniciar sesión' : 'Sign In'}
          </Link>
        </div>
      </header>

      <main className="landing-main">
        <div className="landing-hero-copy">
          <h1>{spanish ? 'Películas y series ilimitadas y mucho más' : 'Unlimited movies, TV shows, and more'}</h1>
          <p className="landing-price">{spanish ? 'Desde $8.99. Cancela cuando quieras.' : 'Starts at $8.99. Cancel anytime.'}</p>
          <p className="landing-cta-copy">{spanish ? '¿Quieres ver algo? Ingresa tu correo para crear o reiniciar tu membresía.' : 'Ready to watch? Enter your email to create or restart your membership.'}</p>
          <form className="email-cta" onSubmit={start}>
            <label className={`floating-field ${email ? 'filled' : ''}`}>
              <input
                id="landing-email"
                type="email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value)
                  setError('')
                }}
                placeholder=" "
                autoComplete="email"
              />
              <span>{spanish ? 'Correo electrónico' : 'Email address'}</span>
            </label>
            <button type="submit" className="get-started-button">
              {spanish ? 'Comenzar' : 'Get Started'}
              <AssetIcon name="chevron_right" size={22} />
            </button>
          </form>
          {error ? <p className="form-error landing-error">{error}</p> : null}
        </div>
      </main>

      <section className="landing-promo">
        <div className="landing-promo-copy">
          <h2>The Netflix you love for just $8.99.</h2>
          <p>Get our most affordable, ad-supported plan.</p>
        </div>
        <Link to="/signup" className="promo-learn-more">Learn More</Link>
      </section>

      <footer className="landing-footer">
        <p>Questions? Visit the Help Centre.</p>
        <div>
          <Link to="/login">Sign In</Link>
          <Link to="/signup">Create account</Link>
          <Link to="/browse">Browse catalog</Link>
        </div>
        <p className="footer-copy">Netflix Clone</p>
      </footer>
    </div>
  )
}
