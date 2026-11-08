import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from '../components/Icon'

const collage = [
  'movie_1275779.jpg', 'tv_66732.jpg', 'movie_1003596.jpg', 'movie_1368337.jpg',
  'tv_94997.jpg', 'movie_1315772.jpg', 'movie_1084244.jpg', 'tv_125988.jpg',
  'movie_969681.jpg', 'movie_1339713.jpg', 'tv_37854.jpg', 'movie_931285.jpg',
  'movie_1081003.jpg', 'tv_278624.jpg', 'movie_1108427.jpg', 'movie_687163.jpg',
  'tv_60625.jpg', 'movie_1468683.jpg',
].filter((name, index, arr) => arr.indexOf(name) === index)

export default function Landing() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')

  const start = (event) => {
    event.preventDefault()
    navigate(`/signup${email.trim() ? `?email=${encodeURIComponent(email.trim())}` : ''}`)
  }

  return (
    <div className="landing-page">
      <div className="landing-collage" aria-hidden="true">
        {collage.map((image, index) => (
          <div className={`collage-tile tile-${index}`} key={image}>
            <img src={`/assets/posters/${image}`} alt="" onError={event => { event.currentTarget.style.display = 'none' }} />
          </div>
        ))}
      </div>
      <div className="landing-overlay" />
      <header className="landing-header">
        <img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" className="landing-logo" />
        <button className="btn btn-red btn-small" onClick={() => navigate('/login')}>Sign In</button>
      </header>
      <main className="landing-main">
        <div className="landing-hero-text">
          <h1>Unlimited movies, TV shows, and more</h1>
          <p className="landing-price">Starts at $8.99. Cancel anytime.</p>
          <p className="landing-ready">Ready to watch? Enter your email to create or restart your membership.</p>
          <form className="landing-email-form" onSubmit={start}>
            <label className="email-field">
              <input
                type="email"
                value={email}
                onChange={event => setEmail(event.target.value)}
                placeholder=" "
                aria-label="Email address"
              />
              <span>Email address</span>
            </label>
            <button className="btn btn-red btn-get-started" type="submit">Get Started <Icon name="chevron-right" size={24} /></button>
          </form>
        </div>
      </main>
      <div className="landing-curve" />
      <footer className="landing-footer">
        <div className="landing-promo-copy">
          <strong>The Netflix you love for just $8.99.</strong>
          <span>Get our most affordable, ad-supported plan.</span>
        </div>
        <button className="landing-promo-link" onClick={() => navigate('/signup')}>Learn More <Icon name="chevron-right" size={22} /></button>
      </footer>
    </div>
  )
}
