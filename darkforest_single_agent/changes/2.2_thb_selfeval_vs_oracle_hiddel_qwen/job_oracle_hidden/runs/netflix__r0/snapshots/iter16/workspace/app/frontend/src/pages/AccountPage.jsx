import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import { useApp } from '../state/AppContext'
import { avatarStyle } from '../lib/util'

export default function AccountPage() {
  const { user, profiles, createProfile, updateProfile, deleteProfile, logout } = useApp()
  const nav = useNavigate()
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newAvatar, setNewAvatar] = useState('avatar_3')
  const [renaming, setRenaming] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [msg, setMsg] = useState('')

  const AVATARS = ['avatar_0', 'avatar_1', 'avatar_2', 'avatar_3', 'avatar_4', 'avatar_5']

  const add = async (e) => {
    e.preventDefault()
    if (!newName.trim()) return
    try { await createProfile({ name: newName.trim(), avatar: newAvatar }); setAdding(false); setNewName(''); }
    catch (err) { setMsg(err.message) }
  }

  return (
    <div className="grid-page">
      <Header />
      <h1>Account</h1>
      {msg && <div style={{ color: '#e5e5e5', marginBottom: 12 }}>{msg}</div>}
      <div className="account-card">
        <h2>Membership</h2>
        <div className="account-row"><span>Email</span><span>{user?.email || '—'}</span></div>
        <div className="account-row"><span>Name</span><span>{user?.name || '—'}</span></div>
        <div className="account-row">
          <span>Plan</span>
          <span>Standard — 1080p · 2 screens · ads-free</span>
        </div>
      </div>
      <div className="account-card">
        <h2>Profiles ({profiles.length})</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, margin: '14px 0' }}>
          {profiles.map((p) => (
            <div key={p.id} className="account-row" style={{ border: 'none', padding: '6px 0' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ width: 40, height: 40, borderRadius: 6, background: avatarStyle(p.avatar).bg, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 1.4 }}>
                  {avatarStyle(p.avatar).face}
                </span>
                {renaming === p.id ? (
                  <input
                    className="rename-input"
                    style={{ width: 180, fontSize: 0.95 }}
                    value={renameValue}
                    autoFocus
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && updateProfile(p.id, { name: renameValue.trim() }).then(() => setRenaming(null))}
                  />
                ) : (
                  <span>{p.name}{p.is_kids ? ' (Kids)' : ''}</span>
                )}
              </span>
              <span>
                <button className="btn btn-info" style={{ padding: '5px 12px', fontSize: '0.8rem', marginRight: 8 }} onClick={() => { setRenaming(p.id); setRenameValue(p.name) }}>Rename</button>
                <button className="btn btn-info" style={{ padding: '5px 12px', fontSize: '0.8rem' }} onClick={() => deleteProfile(p.id).catch((e) => setMsg(e.message))}>Delete</button>
              </span>
            </div>
          ))}
        </div>
        {adding ? (
          <form onSubmit={add} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <input type="text" placeholder="Profile name" value={newName} onChange={(e) => setNewName(e.target.value)} style={{ flex: 1, minWidth: 160, padding: 10, background: '#2f2f2f', border: '1px solid #555', color: '#fff' }} />
            <select className="filter-select" value={newAvatar} onChange={(e) => setNewAvatar(e.target.value)} aria-label="Avatar">
              {AVATARS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <button className="btn btn-red" type="submit" style={{ padding: '8px 16px', fontSize: '0.9rem' }}>Add</button>
            <button className="btn btn-info" type="button" style={{ padding: '8px 16px', fontSize: '0.9rem' }} onClick={() => setAdding(false)}>Cancel</button>
          </form>
        ) : (
          <button className="btn btn-red" style={{ padding: '8px 16px', fontSize: '0.9rem' }} onClick={() => setAdding(true)}>+ Add Profile</button>
        )}
      </div>
      <div style={{ color: '#707070', fontSize: 0.85, marginBottom: 30 }}>
        <button className="linkish" style={{ background: 'none', border: 'none', color: '#707070', textDecoration: 'underline' }} onClick={() => { logout(); nav('/') }}>Sign out of all browsers on this device</button>
      </div>
    </div>
  )
}
