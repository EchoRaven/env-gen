import { Link } from 'react-router-dom';
import Row from '../components/Row';
import { API } from '../api';
import { useApi } from '../hooks';

// The catalog (dataset/titles.json) contains no games, so this page is honest about it and
// offers the family titles that are actually in the catalog.
export default function Games() {
  const [genres] = useApi(() => API.genres());
  const family = genres?.find((g) => g.name === 'Family');
  const animation = genres?.find((g) => g.name === 'Animation');
  const [familyTitles] = useApi(() => (family ? API.genreTitles(family.id) : Promise.resolve([])), [family?.id]);
  const [animTitles] = useApi(() => (animation ? API.genreTitles(animation.id) : Promise.resolve([])), [animation?.id]);
  const hero = familyTitles && familyTitles[0];
  return (
    <div className="page games">
      <section className="games-hero" style={hero ? { backgroundImage: `url(${hero.backdrop})` } : undefined}>
        <div className="games-shade" />
        <div className="games-content">
          <img className="bb-netflix" src="/assets/brand/netflix_wordmark.svg" alt="" />
          <h1>Games</h1>
          <div className="bb-meta"><span>Game</span><i className="dot" /><span>0 available</span></div>
          <p className="games-empty" data-testid="games-empty">
            There are no games in this catalog yet. When games are added they will appear here.
          </p>
          <div className="bb-buttons">
            {family && <Link className="btn btn-play small" to={`/browse/genre/${family.id}`}>Browse Family Titles</Link>}
            <Link className="btn btn-info small" to="/browse">Back to Home</Link>
          </div>
        </div>
      </section>
      <div className="rows">
        <Row title="Party Games" titles={[]} emptyText="—  No games available" />
        <Row title="Family Movie & Show Night" titles={familyTitles} link={family ? `/browse/genre/${family.id}` : undefined} />
        <Row title="Animated Picks" titles={animTitles} link={animation ? `/browse/genre/${animation.id}` : undefined} />
      </div>
    </div>
  );
}
