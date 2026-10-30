import { useMemo } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import Row from '../components/Row';
import TitleCard from '../components/TitleCard';
import { API } from '../api';
import { useApi } from '../hooks';

export default function GenreCategory() {
  const { genreId } = useParams();
  const [params] = useSearchParams();
  const kind = params.get('kind');
  const [genre, gErr] = useApi(() => API.genre(genreId), [genreId]);
  const [titles] = useApi(() => API.genreTitles(genreId, kind ? { kind } : {}), [genreId, kind]);
  const suffix = kind === 'series' ? 'TV Shows' : kind === 'movie' ? 'Movies' : 'Movies & TV';
  const parent = kind === 'series' ? ['/shows', 'TV Shows'] : kind === 'movie' ? ['/movies', 'Movies'] : ['/browse', 'Home'];
  const newest = useMemo(() => (titles ? [...titles].sort((a, b) => b.year - a.year) : null), [titles]);
  const backdrop = titles && titles[0] ? titles[0].backdrop : null;
  if (gErr) return <div className="page empty-page"><h1>Genre not found</h1><Link to="/browse">Back to Home</Link></div>;
  return (
    <div className="page genre-page">
      <div className="genre-header">
        <Link to={parent[0]} className="crumb">{parent[1]}</Link>
        <span className="crumb-sep">›</span>
        <h1>{genre && !Array.isArray(genre) ? `${genre.name} ${suffix}` : ''}</h1>
      </div>
      <div className="genre-bg" style={backdrop ? { backgroundImage: `url(${backdrop})` } : undefined} />
      <div className="rows genre-rows">
        {titles && titles.length === 0 && <p className="row-empty big">No titles in this genre for this profile — </p>}
        <Row title="Your Next Watch" titles={titles} />
        <Row title="New on Netflix" titles={newest} />
        {titles && titles.length > 0 && (
          <section className="grid-section">
            <h2 className="row-title">All {genre && !Array.isArray(genre) ? genre.name : ''} {suffix}</h2>
            <div className="title-grid">
              {titles.map((t) => <TitleCard key={t.id} title={t} />)}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
