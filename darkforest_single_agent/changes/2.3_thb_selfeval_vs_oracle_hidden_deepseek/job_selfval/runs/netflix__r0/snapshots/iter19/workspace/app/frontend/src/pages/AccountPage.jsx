import { Link, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import Icon from '../components/Icon.jsx'
import { useTitleOverlay } from '../components/useTitleOverlay.js'

export default function AccountPage() {
  const { user, profiles, activeProfile, logout, api } = useAuth()
  const navigate = useNavigate()
  const { openTitle } = useTitleOverlay()
  const [stats, setStats] = useState({ myList: null, continueWatching: null, ratings: null })
  const [ratedTitles, setRatedTitles] = useState([])

  useEffect(() => {
    if (!activeProfile) {
      setStats({ myList: null, continueWatching: null, ratings: null })
      return
    }
    let cancelled = false
    Promise.all([api.get('/api/my-list'), api.get('/api/continue-watching'), api.get('/api/ratings')])
      .then(([myList, continueWatching, ratings]) => {
        if (cancelled) return
        setStats({ myList: myList.total || 0, continueWatching: continueWatching.total || 0, ratings: ratings.total || 0 })
        setRatedTitles(ratings.items || [])
      })
      .catch(() => {
        if (!cancelled) setStats({ myList: '—', continueWatching: '—', ratings: '—' })
      })
    return () => { cancelled = true }
  }, [api, activeProfile])

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
          <h2>Current profile activity</h2>
          {activeProfile ? (
            <>
              <div className="activity-stats">
                <Link to="/my-list" className="activity-stat"><strong>{stats.myList ?? '…'}</strong><span>titles in My List</span></Link>
                <Link to="/browse" className="activity-stat"><strong>{stats.continueWatching ?? '…'}</strong><span>titles in Continue Watching</span></Link>
                <div className="activity-stat"><strong>{stats.ratings ?? '…'}</strong><span>titles rated</span></div>
                <div className="activity-stat"><strong>{activeProfile.is_kids ? 'Kids' : 'Standard'}</strong><span>profile type</span></div>
              </div>
              <div className="account-ratings">
                <h3>Your ratings</h3>
                {ratedTitles.length ? (
                  <div className="account-rating-list">
                    {ratedTitles.slice(0, 6).map((entry) => (
                      <button key={entry.id} type="button" className="account-rating-item" onClick={() => openTitle({ id: entry.title_id })}>
                        <img src={entry.poster} alt="" />
                        <span><strong>{entry.title_name}</strong><small>{entry.value === 2 ? 'Loved' : entry.value === 1 ? 'Liked' : 'Not for me'}</small></span>
                        <Icon name={entry.value === -1 ? 'thumbs-down' : 'thumbs-up'} size={16} />
                      </button>
                    ))}
                  </div>
                ) : <p className="account-copy">No ratings yet for this profile.</p>}
              </div>
            </>
          ) : <p className="account-copy">Select a profile to view its private activity.</p>}
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
