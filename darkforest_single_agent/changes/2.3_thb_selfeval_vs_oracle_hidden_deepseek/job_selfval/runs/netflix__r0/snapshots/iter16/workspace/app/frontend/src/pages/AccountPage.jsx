import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import Icon from '../components/Icon.jsx'

export default function AccountPage() {
  const { user, profiles, activeProfile, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <PageShell className="browse-app account-page">
      <div className="browse-main account-main">
        <h1>Account</h1>
        <section className="account-panel">
          <div className="account-panel-heading">
            <h2>Membership &amp; Account</h2>
            <span className="account-avatar-chip"><img src={activeProfile?.avatar || profiles[0]?.avatar || '/assets/avatars/avatar_1.svg'} alt="" />{activeProfile?.name || profiles[0]?.name || 'Profile'}</span>
          </div>
          <div className="account-info-grid">
            <div><span>Name</span><strong>{user?.name || '—'}</strong></div>
            <div><span>Email</span><strong>{user?.email || '—'}</strong></div>
            <div><span>Profiles</span><strong>{profiles.length}</strong></div>
            <div><span>Current profile</span><strong>{activeProfile?.name || 'None selected'}</strong></div>
          </div>
          <div className="account-actions">
            <Link to="/profiles" className="btn btn-play"><Icon name="plus" size={20} /> Manage Profiles</Link>
            <button type="button" className="btn btn-info" onClick={() => { logout(); navigate('/') }}>Sign out of Netflix</button>
          </div>
        </section>
        <section className="account-panel">
          <h2>Profile privacy</h2>
          <p className="account-copy">My List, ratings and Continue Watching are stored against the active profile. Switching profiles can never reveal another profile's private activity.</p>
          <div className="profile-summary-row">
            {profiles.map((profile) => (
              <div className="profile-summary" key={profile.id}>
                <img src={profile.avatar} alt="" />
                <span>{profile.name}{profile.is_kids ? ' · Kids' : ''}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </PageShell>
  )
}
