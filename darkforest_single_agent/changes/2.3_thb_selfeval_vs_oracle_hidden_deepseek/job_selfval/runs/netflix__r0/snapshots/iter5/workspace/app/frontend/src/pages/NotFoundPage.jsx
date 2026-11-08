import { Link } from 'react-router-dom'
import { BrandLogo } from '../components/Icon.jsx'

export default function NotFoundPage() {
  return (
    <div className="not-found-page">
      <Link to="/"><BrandLogo /></Link>
      <div className="not-found-copy">
        <p className="eyebrow">LOST YOUR WAY?</p>
        <h1>Page not found</h1>
        <p>We couldn't find that page. Head back to the catalog and keep browsing.</p>
        <Link className="btn btn-play" to="/browse">Go to Home</Link>
      </div>
    </div>
  )
}
