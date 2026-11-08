import { Link } from 'react-router-dom'

export default function Logo({ to = '/', className = '', width = 98 }) {
  return (
    <Link className={`logo ${className}`} to={to} aria-label="Netflix home">
      <img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" style={{ width }} />
    </Link>
  )
}
