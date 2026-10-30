import { useEffect, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useSession } from '../session.jsx'
import { PencilIcon } from '../icons.jsx'
import Avatar, { AVATAR_CHOICES } from '../components/Avatar.jsx'

function ProfileEditor({ initial, onDone, canDelete }) {
  const { refreshProfiles, profile, selectProfile, flash } = useSession()
  const [name, setName] = useState(initial?.name || '')
  const [avatar, setAvatar] = useState(initial?.avatar || 'blue')
  const [isKids, setIsKids] = useState(!!initial?.is_kids)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async (e) => {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const body = { name: name.trim(), avatar, is_kids: isKids }
      if (initial) await api.updateProfile(initial.id, body)
      else await api.createProfile(body)
      await refreshProfiles()
      flash(initial ? 'Profile updated' : `Profile "${body.name}" created`)
      onDone()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!window.confirm(`Delete profile "${initial.name}"? Its My List, ratings and history will be removed.`)) return
    setBusy(true)
    try {
      await api.deleteProfile(initial.id)
      if (profile && profile.id === initial.id) selectProfile(null)
      await refreshProfiles()
      flash('Profile deleted')
      onDone()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return (
    <form className="profile-editor" onSubmit={save}>
      <h1>{initial ? 'Edit Profile' : 'Add Profile'}</h1>
      {!initial && <p className="pe-sub">Add a profile for another person watching Netflix.</p>}
      <div className="pe-body">
        <Avatar avatar={avatar} size={140} />
        <div className="pe-fields">
          <input className="pe-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name"
            maxLength={30} required aria-label="Profile name" />
          <div className="pe-label">Choose an icon</div>
          <div className="pe-avatars">
            {AVATAR_CHOICES.map((a) => (
              <button type="button" key={a} className={`pe-av ${a === avatar ? 'on' : ''}`} aria-label={`Icon ${a}`}
                onClick={() => setAvatar(a)}><Avatar avatar={a} size={56} /></button>
            ))}
          </div>
          <label className="pe-kids">
            <input type="checkbox" checked={isKids} onChange={(e) => setIsKids(e.target.checked)} />
            <span>Kids profile — only shows family &amp; animation titles</span>
          </label>
          {error && <div className="auth-error">{error}</div>}
        </div>
      </div>
      <div className="pe-actions">
        <button type="submit" className="pe-btn primary" disabled={busy}>Save</button>
        <button type="button" className="pe-btn" onClick={onDone}>Cancel</button>
        {initial && canDelete && <button type="button" className="pe-btn" onClick={remove} disabled={busy}>Delete Profile</button>}
      </div>
    </form>
  )
}

export default function Profiles() {
  const { token, profiles, selectProfile, refreshProfiles } = useSession()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const manage = params.get('manage') === '1'
  const [editing, setEditing] = useState(null) // profile | 'new' | null
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    if (token) refreshProfiles().catch(() => {}).finally(() => setLoaded(true))
  }, [token, refreshProfiles])
  if (!token) return <Navigate to="/login" replace />

  const choose = (p) => {
    if (manage) { setEditing(p); return }
    selectProfile(p)
    navigate('/browse')
  }

  return (
    <div className="profiles-page">
      <header className="auth-header slim">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="auth-logo sm" />
      </header>
      {!loaded && profiles.length === 0 ? <div className="spinner" /> : editing ? (
        <ProfileEditor initial={editing === 'new' ? null : editing} canDelete={profiles.length > 1} onDone={() => setEditing(null)} />
      ) : (
        <div className="who">
          <h1>{manage ? 'Manage Profiles:' : 'Who’s watching?'}</h1>
          <div className="who-grid">
            {profiles.map((p) => (
              <button key={p.id} className="who-item" onClick={() => choose(p)}>
                <span className="who-av">
                  <Avatar avatar={p.avatar} size={160} />
                  {manage && <span className="who-edit"><PencilIcon size={44} /></span>}
                </span>
                <span className="who-name">{p.name}</span>
              </button>
            ))}
            {profiles.length < 5 && (
              <button className="who-item" onClick={() => setEditing('new')}>
                <span className="who-av add">+</span>
                <span className="who-name">Add Profile</span>
              </button>
            )}
          </div>
          {manage
            ? <button className="manage-btn done" onClick={() => setParams({})}>Done</button>
            : <button className="manage-btn" onClick={() => setParams({ manage: '1' })}>Manage Profiles</button>}
        </div>
      )}
    </div>
  )
}
