import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BrandLogo } from '../components/Icon.jsx'
import { useAuth } from '../context/AuthContext.jsx'

const POSTERS = [
  '/assets/posters/movie_1275779.jpg', '/assets/posters/movie_1368337.jpg', '/assets/posters/movie_1083381.jpg',
  '/assets/posters/movie_1273221.jpg', '/assets/posters/movie_1228710.jpg', '/assets/posters/movie_1339713.jpg',
  '/assets/posters/movie_969681.jpg', '/assets/posters/movie_1318621.jpg', '/assets/posters/movie_1284465.jpg',
  '/assets/posters/movie_1108427.jpg', '/assets/posters/movie_1003596.jpg', '/assets/posters/movie_1280738.jpg',
  '/assets/posters/movie_1400837.jpg', '/assets/posters/movie_1468683.jpg', '/assets/posters/movie_1084244.jpg',
  '/assets/posters/movie_1212763.jpg', '/assets/posters/movie_1440050.jpg', '/assets/posters/movie_931285.jpg',
  '/assets/posters/movie_1315772.jpg', '/assets/posters/movie_1314481.jpg', '/assets/posters/tv_279323.jpg',
  '/assets/posters/tv_94997.jpg', '/assets/posters/tv_298610.jpg', '/assets/posters/tv_321564.jpg',
]

export default function LandingPage() {
  const navigate = useNavigate()
  const { token } = useAuth()
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const columns = useMemo(() => {
    const rows = Array.from({ length: 12 }, () => [])
    POSTERS.forEach((poster, index) => rows[index % rows.length].push(poster))
    return rows
  }, [])

  function start(event) {
    event.preventDefault()
    const value = email.trim()
    if (!value || !/^\S+@\S+\.\S+$/.test(value)) {
      setError('Please enter a valid email address.')
      return
    }
    navigate(`/signup?email=${encodeURIComponent(value)}`)
  }

  return (
    <div className="landing-page">
      <div className="landing-wall" aria-hidden="true">
        {columns.map((column, columnIndex) => (
          <div className="landing-column" key={columnIndex}>
            {column.concat(column).map((poster, index) => <img key={`${poster}-${index}`} src={poster} alt="" />)}
          </div>
        ))}
      </div>
      <div className="landing-shade" />
      <header className="landing-header">
        <Link to="/" aria-label="Netflix home"><BrandLogo /></Link>
        {token ? <Link className="btn btn-red btn-small" to="/profiles">Browse</Link> : <Link className="signin-link" to="/login">Sign In</Link>}
      </header>
      <main className="landing-content">
        <div className="landing-copy">
          <h1>Unlimited movies, TV shows, and more</h1>
          <p className="landing-subtitle">Starts at $8.99. Cancel anytime.</p>
          <p className="landing-prompt">Ready to watch? Enter your email to create or restart your membership.</p>
          <form className="landing-form" onSubmit={start} noValidate>
            <label className="floating-field">
              <input type="email" value={email} onChange={(event) => { setEmail(event.target.value); setError('') }} placeholder=" " autoComplete="email" />
              <span>Email address</span>
            </label>
            <button type="submit" className="btn btn-red landing-cta">Get Started <span aria-hidden="true">›</span></button>
          </form>
          {error && <p className="landing-error" role="alert">{error}</p>}
        </div>
      </main>
      <div className="landing-bottom-fade" />
    </div>
  )
}
