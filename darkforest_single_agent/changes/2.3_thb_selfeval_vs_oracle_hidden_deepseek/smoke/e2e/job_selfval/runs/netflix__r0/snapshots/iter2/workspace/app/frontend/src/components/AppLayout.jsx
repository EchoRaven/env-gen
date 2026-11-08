import { Outlet, useLocation } from 'react-router-dom'
import Header from './Header'

export default function AppLayout() {
  const location = useLocation()
  return (
    <div className="app-shell">
      <Header />
      <main key={location.pathname} className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
