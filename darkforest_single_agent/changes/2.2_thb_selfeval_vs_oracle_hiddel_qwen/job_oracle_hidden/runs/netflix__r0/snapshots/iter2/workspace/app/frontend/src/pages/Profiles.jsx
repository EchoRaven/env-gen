import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Avatar from '../components/Avatar'
import Icon from '../components/Icon'
import { useApp } from '../state/AppContext'
import { avatarStyle } from '../lib/util'

const AVATAR_CHOICES = ['avatar_0', 'avatar_1', 'avatar_2', 'avatar_3', 'avatar_4', 'avatar_5']

export default function Profiles() {
  const { profiles, selectProfile, createProfile, updateProfile, deleteProfile, user } = useApp()
  const nav = useNavigate()
  const [manage, setManage] = useState(false)
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newAvatar, setNewAvatar] = useState('avatar_3')
  const [newKids, setNewKids] = useState(false)
  const [renaming, setRenaming] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(null)

  const pick = (id) => {
    selectProfile(id).then(() => nav('/browse'))
  }

  const add = async (e) => {
    e.preventDefault()
    if (!newName.trim()) return
    try {
      const { list } = await createProfile({ name: newName.trim(), avatar: newAvatar, is_kids: newKids })
      setAdding(false)
      setNewName('')
      if (list.length) pick(list[list.length - 1].id)
    } catch { /* keep dialog open */ }
  }

  const doDelete = async (id) => {
    try {
      await deleteProfile(id)
    } catch (e) {
      alert(e.message)
    }
    setConfirmDelete(null)
  }

  const doRename = async (id) => {
    if (!renameValue.trim()) { setRenaming(null); return }
    try { await updateProfile(id, { name: renameValue.trim() }) } catch (e) { alert(e.message) }
    setRenaming(null)
  }

  return (
    <div className={`profiles-page ${manage ? 'manage-mode' : ''}`}>
      <div className="profiles-top">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" className="wordmark" />
        <button className="manage-link" onClick={() => setManage((v) => !v)}>
          {manage ? 'Done' : 'Manage Profiles'}
          <Icon name={manage ? 'check' : 'edit'} size={16} />
        </button>
      </div>
      <h1 className="profiles-h1">Who’s watching?</h1>
      <div className="profiles-grid">
        {profiles.map((p) => (
          <div key={p.id} className="profile-tile">
            {renaming === p.id ? (
              <input
                className="rename-input"
                value={renameValue}
                autoFocus
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && doRename(p.id)}
              />
            ) : (
              <button className="profile-pick" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }} onClick={() => pick(p.id)}>
                <span className="profile-avatar-lg" style={{ background: avatarStyle(p.avatar).bg, fontSize: 3.4 }}>
                  <span style={{ filter: 'grayscale(0.05)' }}>{avatarStyle(p.avatar).face}</span>
                </span>
                <span className="pname">{p.name}{p.is_kids ? ' (Kids)' : ''}</span>
              </button>
            )}
            {manage && (
              <div className="pmenu">
                <button className="pm-btn" aria-label="Rename profile" onClick={() => { setRenaming(p.id); setRenameValue(p.name) }}>
                  <Icon name="edit" size={14} />
                </button>
                {confirmDelete === p.id ? (
                  <button className="pm-btn" aria-label="Confirm delete" onClick={() => doDelete(p.id)}>
                    <Icon name="check" size={14} />
                  </button>
                ) : (
                  <button className="pm-btn" aria-label="Delete profile" onClick={() => setConfirmDelete(p.id)}>
                    <Icon name="trash" size={14} />
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
        <button className="profile-pick" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }} onClick={() => setAdding(true)}>
          <span className="add-profile"><Icon name="plus" size={44} /></span>
          <span className="pname">Add Profile</span>
        </button>
      </div>
      <div style={{ color: '#707070', fontSize: 0.85, marginTop: 60 }}>
        Signed in as {user?.email}
      </div>
      {adding && (
        <div className="add-profile-form" onClick={() => setAdding(false)}>
          <form className="add-profile-card" onSubmit={add} onClick={(e) => e.stopPropagation()}>
            <h3>Add Profile</h3>
            <input type="text" placeholder="Profile name" value={newName} maxLength={12} onChange={(e) => setNewName(e.target.value)} autoFocus />
            <div className="avatar-choices">
              {AVATAR_CHOICES.map((a) => (
                <button key={a} type="button" className={`avatar-choice ${newAvatar === a ? 'selected' : ''}`} onClick={() => setNewAvatar(a)}>
                  <span style={{ background: avatarStyle(a).bg, width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4 }}>{avatarStyle(a).face}</span>
                </button>
              ))}
            </div>
            <label className="kids-toggle">
              <input type="checkbox" checked={newKids} onChange={(e) => setNewKids(e.target.checked)} style={{ width: 18, height: 18 }} />
              Kids profile (mature titles are hidden)
            </label>
            <div className="form-actions">
              <button type="button" className="btn-cancel" onClick={() => setAdding(false)}>Cancel</button>
              <button type="submit" className="btn-create" disabled={!newName.trim()}>Create</button>
            </div>
          </form>
        </div>
      )}
      {confirmDelete != null && (
        <div className="add-profile-form" onClick={() => setConfirmDelete(null)}>
          <div className="add-profile-card" onClick={(e) => e.stopPropagation()}>
            <h3>Delete this profile?</h3>
            <p style={{ color: '#a3a3a3' }}>Its My List, ratings and viewing progress will be removed.</p>
            <div className="form-actions">
              <button className="btn-cancel" onClick={() => setConfirmDelete(null)}>Cancel</button>
              <button className="btn-create" onClick={() => doDelete(confirmDelete)}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
