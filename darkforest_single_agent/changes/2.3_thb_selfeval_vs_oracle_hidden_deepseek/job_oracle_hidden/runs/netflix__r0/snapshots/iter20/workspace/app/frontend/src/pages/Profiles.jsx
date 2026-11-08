import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { AssetIcon, Wordmark } from '../icons'
import { PROFILE_COLORS } from '../utils'
import { ProfileAvatar } from '../components/ProfileAvatar'

const COLOR_NAMES = Object.keys(PROFILE_COLORS)

function ProfileForm({ initial, onSubmit, onCancel, busy, error }) {
  const [name, setName] = useState(initial?.name || '')
  const [avatar, setAvatar] = useState(initial?.avatar || 'red')
  const [isKids, setIsKids] = useState(initial?.is_kids || false)

  return (
    <form
      className="profile-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (!name.trim()) return
        onSubmit({ name: name.trim(), avatar, is_kids: isKids })
      }}
    >
      <h2>{initial ? 'Edit Profile' : 'Add a Profile'}</h2>
      <p className="profile-form-copy">Add another profile for someone else in your household.</p>
      <label className="floating-field auth-field profile-name-field">
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder=" " autoFocus maxLength={120} />
        <span>Profile name</span>
      </label>
      <div className="avatar-choice-row" role="radiogroup" aria-label="Avatar color">
        {COLOR_NAMES.map((color) => (
          <button
            type="button"
            key={color}
            className={`avatar-choice ${avatar === color ? 'selected' : ''}`}
            style={{ background: `linear-gradient(145deg, ${PROFILE_COLORS[color][0]}, ${PROFILE_COLORS[color][1]})` }}
            onClick={() => setAvatar(color)}
            aria-label={`${color} avatar`}
            aria-pressed={avatar === color}
          >
            {avatar === color ? '✓' : ''}
          </button>
        ))}
      </div>
      <label className="kids-checkbox">
        <input type="checkbox" checked={isKids} onChange={(event) => setIsKids(event.target.checked)} />
        <span>Kids Profile</span>
      </label>
      {error ? <p className="form-error">{error}</p> : null}
      <div className="profile-form-actions">
        <button type="submit" className="button button-white" disabled={busy || !name.trim()}>
          {busy ? 'Saving…' : initial ? 'Save' : 'Continue'}
        </button>
        <button type="button" className="button button-gray" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  )
}

export default function Profiles() {
  const { profiles, activeProfile, createProfile, updateProfile, deleteProfile, selectProfile, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [managing, setManaging] = useState(new URLSearchParams(location.search).get('manage') === '1')
  const [formMode, setFormMode] = useState(null)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (profiles.length === 0) setFormMode('create')
  }, [profiles.length])

  const choose = (profile) => {
    if (managing) {
      setEditing(profile)
      setFormMode('edit')
      return
    }
    selectProfile(profile)
    navigate('/browse')
  }

  const save = async (payload) => {
    setBusy(true)
    setError('')
    try {
      if (formMode === 'edit' && editing) {
        const updated = await updateProfile(editing.id, payload)
        if (activeProfile?.id === updated.id) selectProfile(updated)
      } else {
        const created = await createProfile(payload)
        selectProfile(created)
      }
      setFormMode(null)
      setEditing(null)
    } catch (requestError) {
      setError(requestError.message || 'Could not save the profile.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!editing) return
    setBusy(true)
    setError('')
    try {
      await deleteProfile(editing.id)
      setFormMode(null)
      setEditing(null)
    } catch (requestError) {
      setError(requestError.message || 'Could not delete the profile.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="profiles-page">
      <header className="profiles-header">
        <Wordmark height={36} />
        <button className="profiles-signout" onClick={() => { logout(); navigate('/') }}>
          Sign out
        </button>
      </header>
      <main className="profiles-main">
        <h1>{managing ? 'Manage Profiles' : "Who's watching?"}</h1>
        <div className="profiles-grid">
          {profiles.map((profile) => (
            <button className="profile-tile" key={profile.id} onClick={() => choose(profile)}>
              <span className={`profile-tile-art ${managing ? 'managing' : ''}`}>
                <ProfileAvatar profile={profile} size={150} />
                {managing ? (
                  <span className="profile-edit-indicator">
                    <AssetIcon name="plus" size={28} />
                  </span>
                ) : null}
              </span>
              <span className="profile-name">
                {profile.name}
                {profile.is_kids ? ' (Kids)' : ''}
              </span>
            </button>
          ))}
          <button className="profile-tile add-profile-tile" onClick={() => { setEditing(null); setFormMode('create') }}>
            <span className="add-profile-art">
              <AssetIcon name="plus" size={42} />
            </span>
            <span className="profile-name">Add Profile</span>
          </button>
        </div>
        <div className="profiles-actions">
          <button className="manage-profiles-button" onClick={() => setManaging((value) => !value)}>
            {managing ? 'Done' : 'Manage Profiles'}
          </button>
        </div>
      </main>
      {formMode ? (
        <div className="modal-backdrop profile-modal-backdrop" onClick={() => !busy && setFormMode(null)}>
          <div className="profile-modal" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" onClick={() => !busy && setFormMode(null)} aria-label="Close profile form">
              <AssetIcon name="close" size={22} />
            </button>
            <ProfileForm
              key={`${formMode}-${editing?.id || 'new'}`}
              initial={editing}
              onSubmit={save}
              onCancel={() => setFormMode(null)}
              busy={busy}
              error={error}
            />
            {formMode === 'edit' && profiles.length > 1 ? (
              <button className="delete-profile-button" onClick={remove} disabled={busy}>
                Delete Profile
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
