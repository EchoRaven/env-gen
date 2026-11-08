import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../context'
import Avatar from '../components/Avatar'
import Icon from '../components/Icon'

const avatarChoices = ['red', 'blue', 'green', 'yellow', 'purple', 'pink']

function ProfileEditor({ profile, onClose, onSaved }) {
  const { refreshProfiles } = useApp()
  const [name, setName] = useState(profile?.name || '')
  const [avatar, setAvatar] = useState(profile?.avatar || 'red')
  const [isKids, setIsKids] = useState(Boolean(profile?.is_kids))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const save = async (event) => {
    event.preventDefault()
    if (!name.trim()) { setError('Enter a profile name.'); return }
    setBusy(true)
    setError('')
    try {
      if (profile) {
        await api(`/api/profiles/${profile.id}`, { method: 'PUT', body: { name: name.trim(), avatar, is_kids: isKids } })
      } else {
        await api('/api/profiles', { method: 'POST', body: { name: name.trim(), avatar, is_kids: isKids } })
      }
      await refreshProfiles(profile?.id)
      onSaved?.()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const remove = async () => {
    if (!profile) return
    if (!window.confirm(`Delete profile “${profile.name}”? Its My List, ratings and viewing progress will be removed.`)) return
    setBusy(true)
    try {
      await api(`/api/profiles/${profile.id}`, { method: 'DELETE' })
      await refreshProfiles()
      onSaved?.()
    } catch (err) { setError(err.message); setBusy(false) }
  }

  return (
    <div className="modal-backdrop profile-modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <form className="profile-editor" onSubmit={save}>
        <button type="button" className="modal-close icon-button" onClick={onClose} aria-label="Close profile editor"><Icon name="close" size={24} /></button>
        <h2>{profile ? 'Edit Profile' : 'Add Profile'}</h2>
        <div className="profile-editor-avatar">
          <Avatar profile={{ name: name || '?', avatar, is_kids: isKids }} size={96} />
        </div>
        <label className="auth-input">
          <input value={name} onChange={event => setName(event.target.value)} placeholder=" " maxLength={24} autoFocus />
          <span>Profile name</span>
        </label>
        <div className="avatar-picker" aria-label="Choose avatar color">
          {avatarChoices.map(color => (
            <button key={color} type="button" className={`avatar-choice ${avatar === color ? 'active' : ''}`} onClick={() => setAvatar(color)} aria-label={`${color} avatar`}>
              <Avatar profile={{ name: name || '?', avatar: color }} size={44} />
            </button>
          ))}
        </div>
        <label className="kids-checkbox">
          <input type="checkbox" checked={isKids} onChange={event => setIsKids(event.target.checked)} />
          <span>Kids Profile</span>
        </label>
        {error && <div className="auth-error">{error}</div>}
        <div className="profile-editor-actions">
          <button type="submit" className="btn btn-red" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
          {profile && <button type="button" className="btn btn-secondary" onClick={remove} disabled={busy}>Delete Profile</button>}
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  )
}

export default function Profiles() {
  const { profiles, profile, selectProfile, refreshProfiles, user } = useApp()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [manage, setManage] = useState(params.get('manage') === '1')
  const [editing, setEditing] = useState(null)
  const [adding, setAdding] = useState(false)
  const [busyId, setBusyId] = useState(null)

  useEffect(() => { refreshProfiles().catch(() => {}) }, [refreshProfiles])

  const choose = (item) => {
    if (manage) { setEditing(item); return }
    setBusyId(item.id)
    selectProfile(item)
    setTimeout(() => navigate('/browse'), 250)
  }

  const toggleManage = () => {
    const next = !manage
    setManage(next)
    if (next) setParams({ manage: '1' })
    else setParams({})
  }

  return (
    <div className="profiles-page">
      <header className="profiles-header">
        <LinkLogo />
        <button className="manage-button" onClick={toggleManage}>{manage ? 'Done' : 'Manage Profiles'}</button>
      </header>
      <main className="profiles-main">
        <h1>Who&apos;s watching?</h1>
        <div className="profiles-grid">
          {profiles.map(item => (
            <button className={`profile-tile ${busyId === item.id ? 'selected' : ''}`} key={item.id} onClick={() => choose(item)}>
              <span className="profile-avatar-frame">
                <Avatar profile={item} size={148} />
                {manage && <span className="profile-edit-overlay"><Icon name="plus" size={28} className="pencil" /><span>Edit</span></span>}
                {busyId === item.id && <span className="profile-selecting" />}
              </span>
              <span className="profile-name">{item.name}{item.is_kids ? ' (Kids)' : ''}</span>
            </button>
          ))}
          <button className="profile-tile add-profile-tile" onClick={() => setAdding(true)}>
            <span className="profile-avatar-frame add-frame"><Icon name="plus" size={62} /></span>
            <span className="profile-name">Add Profile</span>
          </button>
        </div>
        {manage && <p className="manage-hint">Choose a profile to edit or delete it.</p>}
        <button className="manage-button bottom" onClick={toggleManage}>{manage ? 'Done' : 'Manage Profiles'}</button>
      </main>
      <footer className="profiles-footer">
        <p>Signed in as {user?.name || user?.email}</p>
      </footer>
      {(editing || adding) && (
        <ProfileEditor
          profile={editing}
          onClose={() => { setEditing(null); setAdding(false) }}
          onSaved={() => { setEditing(null); setAdding(false) }}
        />
      )}
    </div>
  )
}

function LinkLogo() {
  return <button className="profiles-logo" onClick={() => window.location.assign('/browse')} aria-label="Go to Netflix">
    <img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" />
  </button>
}
