import { Link } from 'react-router-dom'
import { BrandLogo } from '../components/Icon.jsx'

export default function HelpPage() {
  return (
    <div className="help-page">
      <header className="help-header">
        <Link to="/"><BrandLogo /></Link>
        <Link to="/login" className="btn btn-red btn-small">Sign In</Link>
      </header>
      <main className="help-main">
        <h1>Help Center</h1>
        <p className="help-lede">Answers about signing in, profiles, and this catalog clone.</p>
        <section id="faq">
          <h2>Frequently asked questions</h2>
          <h3>How do I sign in?</h3>
          <p>Use the email and password for your account. The seeded demo account is <strong>demo@netflix.com</strong> with password <strong>demo123</strong>.</p>
          <h3>Why can another profile not see my list?</h3>
          <p>My List, ratings, and Continue Watching are stored against the active profile. Use the profile menu to switch or manage profiles.</p>
        </section>
        <section id="account">
          <h2>Account</h2>
          <p>Open the profile menu and choose Account to review your name, email, profiles, and current profile.</p>
        </section>
        <section id="privacy">
          <h2>Privacy</h2>
          <p>This local application stores accounts, profiles, ratings, My List entries, and playback progress in its own Postgres database. It does not send them to an external service.</p>
        </section>
        <section id="plans">
          <h2>Plans and billing</h2>
          <p>This clone does not process payments or subscriptions. The landing-page promotion mirrors the supplied reference design; catalog access is free in this demo environment.</p>
        </section>
        <section id="terms">
          <h2>Terms of Use</h2>
          <p>This is a demonstration application built for a product-specification benchmark. Catalog metadata and artwork come from the supplied dataset and assets.</p>
        </section>
        <section id="about">
          <h2>Corporate information</h2>
          <p>The Netflix wordmark, icons, fonts, and media are used solely as provided reference materials for this clone exercise.</p>
        </section>
        <Link to="/browse" className="btn btn-play">Browse the catalog</Link>
      </main>
    </div>
  )
}
