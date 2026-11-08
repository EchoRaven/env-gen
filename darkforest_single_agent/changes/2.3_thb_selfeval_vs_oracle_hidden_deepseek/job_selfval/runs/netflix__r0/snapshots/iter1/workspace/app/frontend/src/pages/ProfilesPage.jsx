import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BrandLogo } from '../components/Icon.jsx'
import Icon from '../components/Icon.jsx'
import { useAuth } from '../context/AuthContext.jsx'

const AVATARS = [1, 2, 3, 4, 5, 6].map((value) => `/assets/avatars/avatar_${value}.svg`)

export default function ProfilesPage() {
  const navigate = useNavigate()
  const { profiles, activeProfile, selectProfile, createProfile, deleteProfile, logout } = useAuth()
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [avatar, setAvatar] = useState(AVATARS[0])
  const [isKids, setIsKids] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function choose(profile) {
    if (editing) return
    selectProfile(profile)
    navigate('/browse')
  }

  async function add(event) {
    event.preventDefault()
    if (!name.trim()) return setError('Enter a profile name.')
    setBusy(true)
    setError('')
    try {
      await createProfile({ name: name.trim(), avatar, is_kids: isKids })
      setAdding(false)
      setName('')
      setAvatar(AVATARS[0])
      setIsKids(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(profile) {
    if (!window.confirm(`Delete the profile “${profile.name}”? Its My List, ratings and viewing history will be removed.`)) return
    setError('')
    try {
      await deleteProfile(profile.id)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="profiles-page">
      <header className="profiles-header">
        <Link to="/browse"><BrandLogo /></Link>
        <div className="profiles-header-actions">
          <button type="button" className="manage-button" onClick={() => setEditing((value) => !value)}>
            {editing ? <><Icon name="check" size={17} /> Done</> : 'Manage Profiles'}
          </button>
          <button type="button" className="signout-button" onClick={() => { logout(); navigate('/') }}>Sign out</button>
        </div>
      </header>
      <main className="profiles-main">
        <h1>Who's watching?</h1>
        {error && <div className="form-error profiles-error" role="alert">{error}</div>}
        <div className="profile-grid">
          {profiles.map((profile) => (
            <div className={`profile-tile ${activeProfile?.id === profile.id ? 'current' : ''}`} key={profile.id}>
              <button type="button" className="profile-select" onClick={() => choose(profile)} aria-label={`${editing ? 'Edit' : 'Watch as'} ${profile.name}`}>
                <span className={`profile-avatar ${editing ? 'editing' : ''}`}>
                  <img src={profile.avatar} alt="" />
                  {editing && <span className="profile-edit-shade"><Icon name="x" size={20} /></span>}
                </span>
                <span className="profile-name">{profile.name}{profile.is_kids ? <small>KIDS</small> : null}</span>
              </button>
              {editing && (
                <button type="button" className="profile-delete" onClick={() => remove(profile)} aria-label={`Delete ${profile.name}`}><Icon name="x" size={16} /></button>
              )}
            </div>
          ))}
          {profiles.length < 5 && (
            <div className="profile-tile add-tile">
              <button type="button" className="profile-select" onClick={() => { setAdding(true); setError('') }}>
                <span className="profile-avatar add-avatar"><Icon name="plus" size={46} /></span>
                <span className="profile-name">Add Profile</span>
              </button>
            </div>
          )}
        </div>
        <p className="profiles-note">Each profile keeps its own My List, ratings and Continue Watching.</p>
      </main>
      {adding && (
        <div className="profile-modal-overlay" role="dialog" aria-modal="true" aria-label="Add a profile" onClick={(event) => { if (event.target === event.currentTarget) setAdding(false) }}>
          <form className="profile-modal" onSubmit={add}>
            <h2>Add a profile</h2>
            <p>Add another profile for someone else in your household.</p>
            {error && <div className="form-error" role="alert">{error}</div>}
            <div className="avatar-picker">
              {AVATARS.map((option) => (
                <button type="button" key={option} className={avatar === option ? 'selected' : ''} onClick={() => setAvatar(option)} aria-label="Choose avatar">
                  <img src={option} alt="" />
                </button>
              ))}
            </div>
            <label className="floating-field dark"><input value={name} onChange={(event) => setName(event.target.value)} placeholder=" " autoFocus /><span>Profile name</span></label>
            <label className="checkbox-label kids-check"><input type="checkbox" checked={isKids} onChange={(event) => setIsKids(event.target.checked)} /> Kids Profile</label>
            <div className="profile-modal-actions">
              <button type="button" className="btn btn-info" onClick={() => setAdding(false)}>Cancel</button>
              <button type="submit" className="btn btn-play" disabled={busy}>{busy ? 'Saving…' : 'Continue'}</button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
