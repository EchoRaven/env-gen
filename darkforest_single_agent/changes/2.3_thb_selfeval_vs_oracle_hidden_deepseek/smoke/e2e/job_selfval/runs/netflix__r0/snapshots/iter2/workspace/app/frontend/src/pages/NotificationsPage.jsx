import { Link } from 'react-router-dom'
import EmptyState from '../components/EmptyState'
import Logo from '../components/Logo'

export default function NotificationsPage() {
  return (
    <div className="notifications-page">
      <header className="profiles-header"><Logo width={150} /><Link className="btn btn-outline" to="/browse">Back to Netflix</Link></header>
      <main className="notifications-main">
        <span className="page-kicker">UPDATES</span>
        <h1>Notifications</h1>
        <EmptyState title="No notifications yet" message="New season alerts and catalog updates would appear here. The current catalog has no notification records." actionLabel="Browse new titles" actionTo="/new" />
      </main>
    </div>
  )
}
