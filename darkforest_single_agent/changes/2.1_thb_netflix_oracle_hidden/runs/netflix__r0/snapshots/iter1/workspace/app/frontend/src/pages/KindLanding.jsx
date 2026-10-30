import { useMemo } from 'react';
import Billboard from '../components/Billboard';
import Row from '../components/Row';
import GenresMenu from './GenresMenu';
import { API } from '../api';
import { useApi } from '../hooks';

// Shared layout for /shows and /movies: heading + Genres dropdown over a full-bleed hero, then rails.
export default function KindLanding({ kind, heading, firstRow }) {
  const [genres] = useApi(() => API.genres({ kind }), [kind]);
  const [top] = useApi(() => API.top10({ kind }), [kind]);
  const [all] = useApi(() => API.titles({ kind, sort: 'rating', limit: 100 }), [kind]);
  const [newest] = useApi(() => API.titles({ kind, sort: 'new', limit: 20 }), [kind]);
  const hero = useMemo(() => (top && top.length ? top[0] : all && all[0]) || null, [top, all]);
  const genreRows = useMemo(() => {
    if (!all || !genres) return [];
    return genres
      .filter((g) => g.title_count >= 3)
      .sort((a, b) => b.title_count - a.title_count)
      .slice(0, 6)
      .map((g) => ({ g, titles: all.filter((t) => t.genres.includes(g.name)) }));
  }, [all, genres]);
  const suffix = kind === 'series' ? 'TV Shows' : 'Movies';
  return (
    <div className="page kind-landing">
      <div className="sub-header">
        <h1>{heading}</h1>
        <GenresMenu genres={genres} kind={kind} />
      </div>
      {all && all.length === 0 ? <div className="empty-hero">No {suffix.toLowerCase()} are available for this profile.</div> : <Billboard title={hero} variant="full" />}
      <div className="rows overlap">
        <Row title={firstRow} titles={all ? all.slice(0, 20) : null} />
        <Row title={`Top 10 ${suffix} in the U.S. Today`} titles={top} variant="top10" />
        <Row title="New on Netflix" titles={newest} />
        {genreRows.map(({ g, titles }) => (
          <Row key={g.id} title={`${g.name} ${suffix}`} titles={titles} link={`/browse/genre/${g.id}?kind=${kind}`} />
        ))}
      </div>
    </div>
  );
}
