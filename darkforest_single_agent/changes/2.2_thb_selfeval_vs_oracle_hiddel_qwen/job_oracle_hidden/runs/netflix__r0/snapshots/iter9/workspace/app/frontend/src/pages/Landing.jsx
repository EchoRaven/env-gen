import { useState } from 'react'
import { COLLAGE } from '../lib/collage'
import { useNavigate } from 'react-router-dom'

export default function Landing() {
  const nav = useNavigate()
  const [email, setEmail] = useState('')

  const start = (e) => {
    e.preventDefault()
    nav('/login?mode=signup' + (email ? `&email=${encodeURIComponent(email)}` : ''))
  }

  return (
    <div className="landing">
      <div className="landing-collage">
        <div className="collage-grid">
          {COLLAGE.map((p, i) => (
            <img key={i} src={p} alt="" loading="lazy" />
          ))}
        </div>
      </div>
      <div className="landing-top">
        <span style={{ color: '#e5e5e5', fontSize: 0.85 }}>
          {email ? 'Hi, ' + email.split('@')[0] + ' — welcome back!' : 'Unlimited movies, TV shows and more'}
        </span>
        <button className="sign-in" onClick={() => nav('/login')}>Sign In</button>
      </div>
      <div className="landing-center">
        <img className="big-wordmark" src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" />
        <h1>Watch anywhere. <br />Cancel anytime.</h1>
        <form className="landing-cta" onSubmit={start}>
          <div className="landing-email-row">
            <input
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-label="Email address"
            />
            <button type="submit" disabled={!email.includes('@')}>
              Get Started <span aria-hidden="true">›</span>
            </button>
          </div>
          <div className="landing-fine">
            Ready to watch? <a href="#/login" style={{ color: '#fff', textDecoration: 'underline' }} onClick={(e) => { e.preventDefault(); nav('/login') }}>Sign In now.</a>
          </div>
        </form>
      </div>
    </div>
  )
}
