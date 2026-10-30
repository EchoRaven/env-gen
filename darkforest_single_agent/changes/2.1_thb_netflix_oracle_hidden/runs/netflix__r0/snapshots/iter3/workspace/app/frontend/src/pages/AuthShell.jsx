import { Link } from 'react-router-dom';

export default function AuthShell({ children }) {
  return (
    <div className="auth-page">
      <header className="auth-header">
        <Link to="/" aria-label="Netflix home"><img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" /></Link>
      </header>
      <main className="auth-main">{children}</main>
      <footer className="auth-footer">
        <p>Questions? Use “Get Help” on the sign-in page.</p>
        <div className="auth-footer-links">
          <Link to="/">Home</Link>
          <Link to="/login">Sign In</Link>
          <Link to="/signup">Create Account</Link>
        </div>
      </footer>
    </div>
  );
}
