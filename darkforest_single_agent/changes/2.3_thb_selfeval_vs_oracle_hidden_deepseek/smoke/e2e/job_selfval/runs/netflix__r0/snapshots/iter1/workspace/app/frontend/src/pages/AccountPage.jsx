import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Avatar from '../components/Avatar'
import Icon from '../components/Icon'
import Logo from '../components/Logo'
import { useAuth } from '../context/AuthContext'

export default function AccountPage() {
  const { user, profiles, profile, logout } = useAuth()
  const [expanded, setExpanded] = useState('membership')
  const navigate = useNavigate()

  const signOut = () => { logout(); navigate('/') }

  return (
    <div className="account-page">
      <header className="profiles-header"><Logo width={150} /><Link className="btn btn-outline" to="/browse">Back to Netflix</Link></header>
      <main className="account-main">
        <span className="page-kicker">ACCOUNT</span>
        <h1>Account</h1>
        <div className="account-summary">
          <Avatar profile={profile} size={72} />
          <div>
            <h2>{user?.name}</h2>
            <p>{user?.email} · Current profile: {profile?.name}</p>
          </div>
          <button className="btn btn-outline btn-small" onClick={() => navigate('/manage-profiles')}>Manage Profiles</button>
        </div>
        <section className="account-panels">
          <article className="account-panel">
            <button className="account-panel-head" onClick={() => setExpanded(expanded === 'membership' ? '' : 'membership')} aria-expanded={expanded === 'membership'}>
              <span><Icon name="info" size={22} /> Membership &amp; Billing</span>
              <Icon name="chevronDown" size={18} className={expanded === 'membership' ? 'flip' : ''} />
            </button>
            {expanded === 'membership' ? (
              <div className="account-panel-body">
                <p><strong>Demo catalog access</strong></p>
                <p>This build provides full access to the 60-title catalog. No payment method is attached.</p>
              </div>
            ) : null}
          </article>
          <article className="account-panel">
            <button className="account-panel-head" onClick={() => setExpanded(expanded === 'profiles' ? '' : 'profiles')} aria-expanded={expanded === 'profiles'}>
              <span><Avatar profile={profile} size={26} /> Profile &amp; Parental Controls</span>
              <Icon name="chevronDown" size={18} className={expanded === 'profiles' ? 'flip' : ''} />
            </button>
            {expanded === 'profiles' ? (
              <div className="account-panel-body">
                {profiles.map((row) => <p key={row.id}><strong>{row.name}</strong> · {row.is_kids ? 'Kids' : 'Standard'} profile</p>)}
                <Link className="text-link" to="/manage-profiles">Manage profiles</Link>
              </div>
            ) : null}
          </article>
          <article className="account-panel">
            <button className="account-panel-head" onClick={() => setExpanded(expanded === 'privacy' ? '' : 'privacy')} aria-expanded={expanded === 'privacy'}>
              <span><Icon name="check" size={22} /> Profile Privacy</span>
              <Icon name="chevronDown" size={18} className={expanded === 'privacy' ? 'flip' : ''} />
            </button>
            {expanded === 'privacy' ? (
              <div className="account-panel-body">
                <p>My List, ratings, and Continue Watching are stored separately for each profile and are only readable with a token for this account.</p>
              </div>
            ) : null}
          </article>
        </section>
        <button className="btn btn-ghost account-signout" onClick={signOut}>Sign out of Netflix</button>
      </main>
    </div>
  )
}
