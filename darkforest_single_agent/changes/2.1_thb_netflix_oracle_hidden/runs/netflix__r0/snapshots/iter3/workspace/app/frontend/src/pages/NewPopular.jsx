import Row from '../components/Row';
import { API } from '../api';
import { useApi } from '../hooks';

export default function NewPopular() {
  const [newest] = useApi(() => API.trending({ limit: 20 }));
  const [topTv] = useApi(() => API.top10({ kind: 'series' }));
  const [topMovies] = useApi(() => API.top10({ kind: 'movie' }));
  const [all] = useApi(() => API.titles({ sort: 'new', limit: 60 }));
  const comingThisWeek = all ? all.filter((t) => t.year >= 2026 && !t.top10_rank) : null;
  return (
    <div className="page new-popular">
      <div className="rows top-pad">
        <Row title="New on Netflix" titles={newest} />
        <Row title="Top 10 TV Shows in the U.S. Today" titles={topTv} variant="top10" emptyText="—" />
        <Row title="Top 10 Movies in the U.S. Today" titles={topMovies} variant="top10" emptyText="—" />
        <Row title="Coming This Week" titles={comingThisWeek} emptyText="—" />
        <Row title="Worth the Wait" titles={all ? all.filter((t) => t.year < 2026) : null} />
      </div>
    </div>
  );
}
