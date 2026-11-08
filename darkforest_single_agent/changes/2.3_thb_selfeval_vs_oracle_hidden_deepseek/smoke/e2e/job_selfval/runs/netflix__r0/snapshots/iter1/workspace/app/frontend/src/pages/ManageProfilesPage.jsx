import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import Avatar from '../components/Avatar'
import Icon from '../components/Icon'
import Logo from '../components/Logo'
import Spinner from '../components/Spinner'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'

export default function ManageProfilesPage() {
  const { profiles, setProfiles, setProfile, profile: activeProfile } = useAuth()
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null)
  const [name, setName] = useState('')
  const [isKids, setIsKids] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const { notify } = useToast()

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.get('/api/profiles')
      setProfiles(data.items || [])
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const beginEdit = (profile) => {
    setEditing(profile)
    setName(profile.name)
    setIsKids(profile.is_kids)
    setError('')
  }

  const save = async (event) => {
    event.preventDefault()
    if (!name.trim()) { setError('Enter a profile name.'); return }
    setSaving(true)
    try {
      const data = await api.patch(`/api/profiles/${editing.id}`, { name: name.trim(), is_kids: isKids })
      setProfiles(profiles.map((profile) => profile.id === editing.id ? data.item : profile))
      if (activeProfile?.id === editing.id) setProfile(data.item)
      setEditing(null)
      notify('Profile updated.', 'success')
    } catch (err) { setError(err.message) } finally { setSaving(false) }
  }

  const remove = async (profile) => {
    if (!window.confirm(`Delete the profile “${profile.name}”? Its My List and ratings will also be deleted.`)) return
    try {
      await api.delete(`/api/profiles/${profile.id}`)
      const remaining = profiles.filter((row) => row.id !== profile.id)
      setProfiles(remaining)
      if (activeProfile?.id === profile.id) setProfile(remaining[0] || null)
      setEditing(null)
      notify('Profile deleted.')
    } catch (err) { setError(err.message) }
  }

  return (
    <div className="profiles-page manage-page">
      <header className="profiles-header">
        <Logo width={150} />
        <button className="btn btn-outline" onClick={() => navigate('/profiles')}>Done</button>
      </header>
      <main className="profiles-main">
        <span className="page-kicker">ACCOUNT SETTINGS</span>
        <h1>Manage Profiles</h1>
        {loading ? <Spinner label="Loading profiles…" /> : (
          <div className="manage-grid">
            {profiles.map((profile) => (
              <article key={profile.id} className="manage-card">
                <Avatar profile={profile} size={100} />
                <h3>{profile.name}</h3>
                <span className="manage-type">{profile.is_kids ? 'Kids profile' : 'Standard profile'}</span>
                <div className="manage-card-actions">
                  <button className="btn btn-outline btn-small" onClick={() => beginEdit(profile)}>Edit</button>
                  {profiles.length > 1 ? <button className="btn btn-ghost btn-small" onClick={() => remove(profile)}>Delete</button> : null}
                </div>
              </article>
            ))}
          </div>
        )}
        <button className="btn btn-light" onClick={() => navigate('/profiles')}>Switch Profile</button>
      </main>
      {editing ? (
        <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(null) }}>
          <form className="profile-dialog" onSubmit={save}>
            <button type="button" className="icon-btn dialog-close" onClick={() => setEditing(null)} aria-label="Close edit profile"><Icon name="close" size={22} /></button>
            <h2>Edit Profile</h2>
            <label className="field"><span>Profile name</span><input value={name} onChange={(event) => setName(event.target.value)} maxLength={40} autoFocus /></label>
            <label className="check-field"><input type="checkbox" checked={isKids} onChange={(event) => setIsKids(event.target.checked)} /><span>Kids Profile</span></label>
            {error ? <p className="form-error">{error}</p> : null}
            <button className="btn btn-red" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
          </form>
        </div>
      ) : null}
    </div>
  )
}
