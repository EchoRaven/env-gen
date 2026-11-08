import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import api from '../api'
import Avatar, { avatarChoices } from '../components/Avatar'
import Icon from '../components/Icon'
import Logo from '../components/Logo'
import Spinner from '../components/Spinner'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'

export default function ProfilesPage() {
  const { profiles, setProfiles, setProfile } = useAuth()
  const [manage, setManage] = useState(false)
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [avatar, setAvatar] = useState('violet')
  const [isKids, setIsKids] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const location = useLocation()
  const { notify } = useToast()

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.get('/api/profiles')
      setProfiles(data.items || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (profile) => {
    if (manage) { navigate('/manage-profiles'); return }
    setProfile(profile)
    navigate(location.state?.from || '/browse', { replace: true })
  }

  const createProfile = async (event) => {
    event.preventDefault()
    if (!name.trim()) { setError('Enter a profile name.'); return }
    setSaving(true)
    setError('')
    try {
      const data = await api.post('/api/profiles', { name: name.trim(), avatar, is_kids: isKids })
      const list = [...profiles, data.item]
      setProfiles(list)
      setProfile(data.item)
      setAdding(false)
      setName('')
      notify(`Profile ${data.item.name} created.`, 'success')
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="profiles-page">
      <header className="profiles-header">
        <Logo width={150} />
        <button className="btn btn-outline" onClick={() => navigate('/browse')}>Browse</button>
      </header>
      <main className="profiles-main">
        <h1>{manage ? 'Manage Profiles' : "Who's watching?"}</h1>
        {loading ? <Spinner label="Loading profiles…" /> : (
          <div className="profile-grid">
            {profiles.map((profile) => (
              <button
                key={profile.id}
                className={`profile-tile ${manage ? 'managing' : ''}`}
                onClick={() => choose(profile)}
                aria-label={manage ? `Manage ${profile.name}` : `Watch as ${profile.name}`}
              >
                <span className="profile-avatar-wrap">
                  <Avatar profile={profile} size={148} />
                  {manage ? (
                    <span className="edit-badge"><Icon name="plus" size={22} className="edit-pencil" /></span>
                  ) : null}
                  {profile.is_kids ? <span className="kids-badge">KIDS</span> : null}
                </span>
                <span className="profile-name">{profile.name}</span>
              </button>
            ))}
            {profiles.length < 5 ? (
              <button className="profile-tile add-profile" onClick={() => { setAdding(true); setManage(true); setError('') }}>
                <span className="add-profile-avatar"><Icon name="plus" size={48} /></span>
                <span className="profile-name">Add Profile</span>
              </button>
            ) : null}
          </div>
        )}
        <div className="profiles-actions">
          <button className="btn btn-outline" onClick={() => setManage((value) => !value)}>
            {manage ? 'Done' : 'Manage Profiles'}
          </button>
          {manage ? (
            <button className="btn btn-ghost" onClick={() => navigate('/account')}>Account</button>
          ) : null}
        </div>
      </main>

      {adding ? (
        <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setAdding(false) }}>
          <form className="profile-dialog" onSubmit={createProfile}>
            <button type="button" className="icon-btn dialog-close" onClick={() => setAdding(false)} aria-label="Close add profile"><Icon name="close" size={22} /></button>
            <h2>Add a Profile</h2>
            <p>Add another profile for someone who lives here.</p>
            <label className="field">
              <span>Profile name</span>
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Name" maxLength={40} autoFocus />
            </label>
            <fieldset className="avatar-picker">
              <legend>Avatar</legend>
              <div>
                {avatarChoices.map((choice) => (
                  <button key={choice} type="button" className={`avatar-choice ${avatar === choice ? 'selected' : ''}`} onClick={() => setAvatar(choice)} aria-label={`Choose ${choice} avatar`}>
                    <Avatar profile={{ name: name || 'P', avatar: choice }} size={44} />
                  </button>
                ))}
              </div>
            </fieldset>
            <label className="check-field">
              <input type="checkbox" checked={isKids} onChange={(event) => setIsKids(event.target.checked)} />
              <span>Kids Profile</span>
            </label>
            {error ? <p className="form-error">{error}</p> : null}
            <button className="btn btn-red" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Continue'}</button>
          </form>
        </div>
      ) : null}
    </div>
  )
}
