import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="notfound">
      <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="auth-logo" />
      <h1>Lost your way?</h1>
      <p>Sorry, we can’t find that page. You’ll find lots to explore on the home page.</p>
      <Link to="/browse" className="btn-white">Netflix Home</Link>
    </div>
  )
}
