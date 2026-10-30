import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Avatar from '../components/Avatar';
import { API } from '../api';
import { useStore } from '../store';

const AVATARS = ['blue', 'red', 'yellow', 'green', 'purple', 'kids'];

function ProfileForm({ initial, onSave, onCancel, onDelete, heading }) {
  const [name, setName] = useState(initial?.name || '');
  const [avatar, setAvatar] = useState(initial?.avatar || 'blue');
  const [isKids, setIsKids] = useState(initial?.is_kids || false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setError('Please enter a name'); return; }
    setBusy(true);
    try { await onSave({ name: name.trim(), avatar, is_kids: isKids }); } catch (err) { setError(err.message); setBusy(false); }
  };
  return (
    <form className="profile-form" onSubmit={submit}>
      <h1>{heading}</h1>
      <p className="muted">Add a profile for another person watching Netflix.</p>
      <div className="pf-row">
        <Avatar avatar={avatar} size={120} />
        <div className="pf-fields">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" maxLength={60} aria-label="Profile name" autoFocus />
          <div className="pf-avatars" role="radiogroup" aria-label="Avatar">
            {AVATARS.map((a) => (
              <button type="button" key={a} className={a === avatar ? 'on' : ''} aria-label={`Avatar ${a}`} aria-checked={a === avatar} role="radio" onClick={() => setAvatar(a)}>
                <Avatar avatar={a} size={44} />
              </button>
            ))}
          </div>
          <label className="pf-kids">
            <input type="checkbox" checked={isKids} onChange={(e) => setIsKids(e.target.checked)} />
            <span>Kids profile <small>(only Family &amp; Animation titles)</small></span>
          </label>
          {error && <div className="auth-error">{error}</div>}
        </div>
      </div>
      <div className="pf-actions">
        <button className="btn-white" type="submit" disabled={busy}>Save</button>
        <button className="btn-outline" type="button" onClick={onCancel}>Cancel</button>
        {onDelete && <button className="btn-outline" type="button" onClick={onDelete}>Delete Profile</button>}
      </div>
    </form>
  );
}

export default function Profiles({ manage = false, redirectTo }) {
  const { profiles, selectProfile, loadProfiles, profile: active, logout } = useStore();
  const navigate = useNavigate();
  const loc = useLocation();
  const [editing, setEditing] = useState(null); // profile | 'new' | null
  const target = redirectTo || loc.state?.from || '/browse';

  const choose = (p) => {
    if (manage) { setEditing(p); return; }
    selectProfile(p);
    navigate(target.startsWith('/profiles') ? '/browse' : target, { replace: true });
  };

  if (editing) {
    const isNew = editing === 'new';
    return (
      <div className="profiles-page">
        <ProfileForm
          heading={isNew ? 'Add Profile' : 'Edit Profile'}
          initial={isNew ? null : editing}
          onCancel={() => setEditing(null)}
          onSave={async (b) => {
            if (isNew) await API.createProfile(b); else await API.updateProfile(editing.id, b);
            const list = await loadProfiles();
            if (!isNew && active?.id === editing.id) selectProfile(list.find((p) => p.id === editing.id));
            setEditing(null);
          }}
          onDelete={!isNew && profiles.length > 1 ? async () => {
            await API.deleteProfile(editing.id);
            if (active?.id === editing.id) selectProfile(null);
            await loadProfiles();
            setEditing(null);
          } : null}
        />
      </div>
    );
  }

  return (
    <div className="profiles-page">
      <header className="profiles-header">
        <img src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" />
      </header>
      <div className="profiles-center">
        <h1>{manage ? 'Manage Profiles:' : 'Who’s watching?'}</h1>
        <ul className="profile-grid">
          {profiles.map((p) => (
            <li key={p.id}>
              <button className={`profile-tile ${manage ? 'manage' : ''}`} onClick={() => choose(p)} aria-label={manage ? `Edit ${p.name}` : `Select profile ${p.name}`}>
                <span className="pt-avatar">
                  <Avatar avatar={p.avatar} size={150} radius={6} />
                  {manage && (
                    <span className="pt-edit"><svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.5"><path d="M4 20l4-1 11-11-3-3L5 16l-1 4z" /></svg></span>
                  )}
                </span>
                <span className="pt-name">{p.name}</span>
              </button>
            </li>
          ))}
          {profiles.length < 5 && (
            <li>
              <button className="profile-tile add" onClick={() => setEditing('new')} aria-label="Add Profile">
                <span className="pt-avatar add-avatar">
                  <svg width="70" height="70" viewBox="0 0 24 24" fill="#808080"><path d="M11 11V4h2v7h7v2h-7v7h-2v-7H4v-2z" /></svg>
                </span>
                <span className="pt-name">Add Profile</span>
              </button>
            </li>
          )}
        </ul>
        {manage ? (
          <button className="btn-white wide" onClick={() => navigate(active ? '/browse' : '/profiles')}>Done</button>
        ) : (
          <div className="profiles-actions">
            <Link className="btn-outline wide" to="/profiles/manage">Manage Profiles</Link>
            <button className="link-btn" onClick={() => { logout(); navigate('/'); }}>Sign out</button>
          </div>
        )}
      </div>
    </div>
  );
}
