import { useNavigate } from 'react-router-dom'
import { useSession } from '../session.jsx'
import Avatar from '../components/Avatar.jsx'

export default function Account() {
  const { user, profiles, profile, logout, selectProfile } = useSession()
  const navigate = useNavigate()
  return (
    <div className="grid-page account-page">
      <h1 className="page-title">Account</h1>
      <section className="acct-card">
        <h2>Membership details</h2>
        <p><span className="label">Email</span>{user?.email || '—'}</p>
        <p><span className="label">Name</span>{user?.name || '—'}</p>
      </section>
      <section className="acct-card">
        <h2>Profiles</h2>
        {profiles.map((p) => (
          <div key={p.id} className="acct-profile">
            <Avatar avatar={p.avatar} size={44} />
            <span>{p.name}{p.is_kids ? ' · Kids' : ''}{profile && p.id === profile.id ? ' (current)' : ''}</span>
            {profile && p.id !== profile.id && (
              <button className="btn-grey sm" onClick={() => { selectProfile(p); navigate('/browse') }}>Switch</button>
            )}
          </div>
        ))}
        <button className="btn-grey sm" onClick={() => navigate('/profiles?manage=1')}>Manage Profiles</button>
      </section>
      <button className="btn-red" onClick={logout}>Sign out of Netflix</button>
    </div>
  )
}
