import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useSession } from '../session.jsx'
import { Icon } from '../icons.jsx'
import posters from '../data/posters.js'

export default function Landing() {
  const { token } = useSession()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  if (token) return <Navigate to="/profiles" replace />
  const start = (e) => {
    e.preventDefault()
    navigate(`/signup?email=${encodeURIComponent(email.trim())}`)
  }
  const tiles = [...posters, ...posters].slice(0, 96)
  return (
    <div className="landing">
      <div className="landing-collage" aria-hidden="true">
        <div className="collage-grid">
          {tiles.map((src, i) => <img key={i} src={src} alt="" loading={i < 40 ? 'eager' : 'lazy'} />)}
        </div>
      </div>
      <div className="landing-shade" />
      <header className="landing-header">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="landing-logo" />
        <div className="landing-header-right">
          <label className="lang-select">
            <span className="lang-glyph">文A</span>
            <select aria-label="Language" defaultValue="en"><option value="en">English</option></select>
          </label>
          <Link to="/login" className="btn-red sm">Sign In</Link>
        </div>
      </header>
      <section className="landing-hero">
        <h1>Unlimited movies, TV shows, and more</h1>
        <p className="lh-sub">Watch on any device. Every profile keeps its own list.</p>
        <p className="lh-cta">Ready to watch? Enter your email to create or restart your membership.</p>
        <form className="lh-form" onSubmit={start}>
          <input type="email" required placeholder="Email address" value={email}
            onChange={(e) => setEmail(e.target.value)} aria-label="Email address" />
          <button type="submit" className="btn-red lg">Get Started <Icon name="chevronRight" size={26} /></button>
        </form>
      </section>
      <div className="landing-curve" />
      <section className="landing-banner">
        <div className="banner-card">
          <span className="banner-icon" aria-hidden="true">🍿</span>
          <div>
            <h3>{posters.length} real titles, ready to stream.</h3>
            <p>Create an account to browse the catalog, build My List and pick up where you left off.</p>
          </div>
          <Link to="/signup" className="btn-grey">Learn More</Link>
        </div>
      </section>
    </div>
  )
}
