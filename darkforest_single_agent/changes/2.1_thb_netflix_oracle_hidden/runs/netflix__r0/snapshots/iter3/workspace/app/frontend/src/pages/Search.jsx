import { useSearchParams } from 'react-router-dom';
import TitleCard from '../components/TitleCard';
import { API } from '../api';
import { useApi } from '../hooks';

export default function Search() {
  const [params] = useSearchParams();
  const q = params.get('q') || '';
  const [results] = useApi(() => API.search(q), [q]);
  return (
    <div className="page grid-page">
      <h1 className="page-title small">{q ? <>Results for “{q}”</> : 'Search'}</h1>
      {results === null && <div className="spinner" />}
      {results && results.length === 0 && (
        <div className="empty-state">
          <p>{q ? `Your search for "${q}" did not have any matches.` : 'Type a title or genre in the search box.'}</p>
          {q && <ul className="muted"><li>Try different keywords</li><li>Try a genre, like Comedy or Drama</li></ul>}
        </div>
      )}
      {results && results.length > 0 && (
        <div className="title-grid">{results.map((t) => <TitleCard key={t.id} title={t} />)}</div>
      )}
    </div>
  );
}
