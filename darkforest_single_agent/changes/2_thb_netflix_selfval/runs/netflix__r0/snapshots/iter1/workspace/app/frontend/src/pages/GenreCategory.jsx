import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import Row from '../components/Row.jsx'
import TitleCard from '../components/TitleCard.jsx'

export default function GenreCategory() {
  const { genreId } = useParams()
  const [params] = useSearchParams()
  const kind = params.get('kind') || ''
  const { profileId } = useSession()
  const genre = useAsync(() => api.genre(genreId), [genreId])
  const all = useAsync(() => api.genreTitles(genreId, { kind }), [genreId, kind, profileId])
  const items = all.data?.items || []
  const byRating = [...items].sort((a, b) => (b.rating || 0) - (a.rating || 0))
  const fresh = items.filter((t) => t.year === '2026')
  const name = genre.data?.item?.name || ''
  const section = kind === 'series' ? ['TV Shows', '/shows'] : kind === 'movie' ? ['Movies', '/movies'] : ['Home', '/browse']
  const heading = kind === 'series' ? `${name} TV Shows` : kind === 'movie' ? `${name} Movies` : name
  const bg = items[0]?.backdrop
  return (
    <div className="genre-page">
      <div className="genre-head">
        <Link to={section[1]} className="crumb">{section[0]}</Link>
        <span className="crumb-sep">›</span>
        <h1>{genre.error ? 'Genre not found' : heading}</h1>
      </div>
      <div className="genre-bg" style={bg ? { backgroundImage: `url(${bg})` } : undefined} />
      <div className="rows genre-rows">
        <Row title="Your Next Watch" items={items.slice(0, 12)} loading={all.loading} error={all.error}
          emptyText={`No ${heading || 'titles'} in the catalog for this profile.`} />
        {byRating.length > 3 && <Row title="Critically Acclaimed" items={byRating.slice(0, 12)} />}
        {fresh.length > 0 && <Row title="New on Netflix" items={fresh} />}
        {items.length > 0 && (
          <section className="row">
            <div className="row-head"><h2 className="row-title">All {heading}</h2></div>
            <div className="title-grid">{items.map((t) => <TitleCard key={t.id} t={t} />)}</div>
          </section>
        )}
      </div>
    </div>
  )
}
