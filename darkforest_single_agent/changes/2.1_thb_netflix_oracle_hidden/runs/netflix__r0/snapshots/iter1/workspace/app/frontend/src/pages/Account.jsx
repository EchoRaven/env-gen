import { Link, useNavigate } from 'react-router-dom';
import Avatar from '../components/Avatar';
import { API } from '../api';
import { useApi } from '../hooks';
import { useStore } from '../store';

export default function Account() {
  const { logout, profile } = useStore();
  const navigate = useNavigate();
  const [me] = useApi(() => API.me());
  const [list] = useApi(() => API.myList());
  const [ratings] = useApi(() => API.ratings());
  const [cw] = useApi(() => API.continueWatching());
  return (
    <div className="page account-page">
      <h1 className="page-title">Account</h1>
      {me && !Array.isArray(me) && (
        <div className="account-card">
          <section>
            <h2>Membership</h2>
            <p><span className="muted">Email: </span>{me.email}</p>
            <p><span className="muted">Name: </span>{me.name || '—'}</p>
          </section>
          <section>
            <h2>Profiles</h2>
            <ul className="account-profiles">
              {me.profiles.map((p) => (
                <li key={p.id}><Avatar avatar={p.avatar} size={32} /> {p.name} {p.is_kids && <small className="muted">(Kids)</small>} {profile?.id === p.id && <small className="muted">· watching now</small>}</li>
              ))}
            </ul>
            <Link className="btn btn-info small" to="/profiles/manage">Manage Profiles</Link>
          </section>
          <section>
            <h2>{profile?.name}’s activity</h2>
            <p><span className="muted">My List: </span>{list ? list.length : '…'} titles</p>
            <p><span className="muted">Ratings: </span>{ratings ? ratings.length : '…'}</p>
            <p><span className="muted">Continue Watching: </span>{cw ? cw.length : '…'}</p>
          </section>
          <button className="btn-red" onClick={() => { logout(); navigate('/'); }}>Sign out of Netflix</button>
        </div>
      )}
    </div>
  );
}
