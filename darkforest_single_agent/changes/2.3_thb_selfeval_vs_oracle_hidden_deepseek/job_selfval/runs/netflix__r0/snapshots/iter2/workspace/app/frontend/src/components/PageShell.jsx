import Header from './Header.jsx'
import Footer from './Footer.jsx'

export default function PageShell({ children, className = '' }) {
  return (
    <div className={`app-shell ${className}`}>
      <Header />
      <main>{children}</main>
      <Footer />
    </div>
  )
}
