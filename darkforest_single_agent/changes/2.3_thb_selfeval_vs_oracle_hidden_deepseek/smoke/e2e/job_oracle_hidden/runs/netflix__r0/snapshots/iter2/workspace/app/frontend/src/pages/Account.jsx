import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context'
import Avatar from '../components/Avatar'
import Icon from '../components/Icon'

export default function Account() {
  const { user, profiles, profile, logout } = useApp()
  const navigate = useNavigate()

  const signOut = () => { logout(); navigate('/') }

  return (
    <div className="account-page">
      <div className="account-heading">
        <h1>Account</h1>
        <button className="account-signout" onClick={signOut}>Sign out of Netflix</button>
      </div>
      <div className="account-columns">
        <section className="account-card">
          <div className="account-card-head"><h2>Membership &amp; Account</h2><Icon name="chevron-right" size={24} /></div>
          <p className="account-name">{user?.name || 'Netflix member'}</p>
          <p>{user?.email}</p>
          <p className="muted">Membership plan details are not part of this local catalog experience.</p>
        </section>
        <section className="account-card">
          <div className="account-card-head"><h2>Profile &amp; Parental Controls</h2><Icon name="chevron-right" size={24} /></div>
          <div className="account-profile-row">
            <Avatar profile={profile} size={54} />
            <div><strong>{profile?.name || 'No profile selected'}</strong><span>{profile?.is_kids ? 'Kids profile' : 'Standard profile'}</span></div>
          </div>
          <button className="btn btn-secondary" onClick={() => navigate('/profiles?manage=1')}>Manage Profiles</button>
          <div className="account-profile-list">
            {profiles.map(item => <span key={item.id}>{item.name}</span>)}
          </div>
        </section>
        <section className="account-card">
          <div className="account-card-head"><h2>Privacy &amp; Data</h2><Icon name="chevron-right" size={24} /></div>
          <p>My List, ratings, and Continue Watching are stored separately for each profile on this account.</p>
          <button className="btn btn-secondary" onClick={() => navigate('/my-list')}>View My List</button>
        </section>
      </div>
      <div className="account-detail-grid">
        <div><span>Email</span><strong>{user?.email || '—'}</strong></div>
        <div><span>Active profile</span><strong>{profile?.name || '—'}</strong></div>
        <div><span>Profiles</span><strong>{profiles.length}</strong></div>
        <div><span>Account status</span><strong>Active</strong></div>
      </div>
    </div>
  )
}
