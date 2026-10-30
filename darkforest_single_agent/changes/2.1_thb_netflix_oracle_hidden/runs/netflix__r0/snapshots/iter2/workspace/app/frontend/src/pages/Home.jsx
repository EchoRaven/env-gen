import { useMemo } from 'react';
import Billboard from '../components/Billboard';
import Row from '../components/Row';
import { API } from '../api';
import { useApi } from '../hooks';
import { useStore } from '../store';
import { progressPct } from '../utils';

export default function Home() {
  const { listVersion } = useStore();
  const [trending] = useApi(() => API.trending({ limit: 20 }));
  const [cw] = useApi(() => API.continueWatching());
  const [myList] = useApi(() => API.myList(), [listVersion]);
  const [topTv] = useApi(() => API.top10({ kind: 'series' }));
  const [top] = useApi(() => API.top10());
  const [genres] = useApi(() => API.genres());
  const [newest] = useApi(() => API.titles({ sort: 'new', limit: 20 }));
  const byName = (n) => genres?.find((g) => g.name === n);
  const actionAdv = byName('Action & Adventure');
  const comedy = byName('Comedy');
  const scifi = byName('Sci-Fi & Fantasy');
  const drama = byName('Drama');
  const animation = byName('Animation');
  const [actionTitles] = useApi(() => (actionAdv ? API.genreTitles(actionAdv.id) : Promise.resolve([])), [actionAdv?.id]);
  const [comedyTitles] = useApi(() => (comedy ? API.genreTitles(comedy.id) : Promise.resolve([])), [comedy?.id]);
  const [scifiTitles] = useApi(() => (scifi ? API.genreTitles(scifi.id) : Promise.resolve([])), [scifi?.id]);
  const [dramaTitles] = useApi(() => (drama ? API.genreTitles(drama.id) : Promise.resolve([])), [drama?.id]);
  const [animTitles] = useApi(() => (animation ? API.genreTitles(animation.id) : Promise.resolve([])), [animation?.id]);

  const hero = useMemo(() => {
    if (!trending || !trending.length) return null;
    const series = trending.filter((t) => t.kind === 'series');
    return series[1] || series[0] || trending[0];
  }, [trending]);
  const cwMap = useMemo(() => Object.fromEntries((cw || []).map((c) => [c.title_id, c])), [cw]);

  return (
    <div className="page home">
      {trending && trending.length === 0 ? (
        <div className="empty-hero">No titles are available for this profile yet.</div>
      ) : (
        <Billboard title={hero} variant="inset" />
      )}
      <div className="rows">
        <Row title="Trending Now" titles={trending} testId="row-trending" />
        <Row title="Continue Watching" titles={cw ? cw.map((c) => c.title) : null} progressFor={(t) => progressPct(cwMap[t.id] || {})} testId="row-continue" />
        <Row title="TV Action & Adventure" titles={actionTitles} link={actionAdv ? `/browse/genre/${actionAdv.id}` : undefined} />
        <Row title="Top 10 TV Shows in the U.S. Today" titles={topTv} variant="top10" />
        <Row title="My List" titles={myList ? myList.map((m) => m.title) : null} link="/my-list" />
        <Row title="Top Searches" titles={top} />
        <Row title="New on Netflix" titles={newest} />
        <Row title="Comedies" titles={comedyTitles} link={comedy ? `/browse/genre/${comedy.id}` : undefined} />
        <Row title="Sci-Fi & Fantasy" titles={scifiTitles} link={scifi ? `/browse/genre/${scifi.id}` : undefined} />
        <Row title="Dramas" titles={dramaTitles} link={drama ? `/browse/genre/${drama.id}` : undefined} />
        <Row title="Animation" titles={animTitles} link={animation ? `/browse/genre/${animation.id}` : undefined} />
      </div>
    </div>
  );
}
