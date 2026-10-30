import TitleCard from '../components/TitleCard';
import { API } from '../api';
import { useApi } from '../hooks';
import { useStore } from '../store';
import { Link } from 'react-router-dom';

export default function MyList() {
  const { listVersion } = useStore();
  const [items] = useApi(() => API.myList(), [listVersion]);
  return (
    <div className="page grid-page">
      <h1 className="page-title">My List</h1>
      {items === null && <div className="spinner" />}
      {items && items.length === 0 && (
        <div className="empty-state" data-testid="mylist-empty">
          <p>You haven’t added any titles to your list yet.</p>
          <Link className="btn btn-info small" to="/browse">Browse titles</Link>
        </div>
      )}
      {items && items.length > 0 && (
        <div className="title-grid" data-testid="mylist-grid">
          {items.map((m) => <TitleCard key={m.id} title={m.title} />)}
        </div>
      )}
    </div>
  );
}
