import { Link } from 'react-router-dom'

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-social">
        <Link to="/browse">Home</Link>
        <Link to="/shows">Shows</Link>
        <Link to="/movies">Movies</Link>
        <Link to="/games">Games</Link>
        <Link to="/new">New & Popular</Link>
        <Link to="/my-list">My List</Link>
      </div>
      <p>Netflix clone catalog · Built with the supplied title catalog and trailer assets.</p>
      <p className="footer-copy">© 2026 Netflix Clone</p>
    </footer>
  )
}
