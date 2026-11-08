import { Link } from 'react-router-dom'

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <p>Questions? Browse the catalog or manage your profiles.</p>
        <div className="footer-links">
          <Link to="/browse">Home</Link>
          <Link to="/shows">Shows</Link>
          <Link to="/movies">Movies</Link>
          <Link to="/new">New &amp; Popular</Link>
          <Link to="/my-list">My List</Link>
          <Link to="/account">Account</Link>
        </div>
        <span className="footer-copy">Netflix clone · Catalog data and artwork from the provided dataset.</span>
      </div>
    </footer>
  )
}
