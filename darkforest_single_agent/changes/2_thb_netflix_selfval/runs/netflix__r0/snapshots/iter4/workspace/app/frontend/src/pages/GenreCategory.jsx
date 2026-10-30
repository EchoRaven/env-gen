import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import Billboard from '../components/Billboard.jsx'
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
  const hero = byRating[0]
  const crumbs = (
    <div className="genre-head over">
      <Link to={section[1]} className="crumb">{section[0]}</Link>
      <span className="crumb-sep">›</span>
      <h1>{genre.error ? 'Genre not found' : heading}</h1>
    </div>
  )
  const empty = !all.loading && !all.error && items.length === 0

  return (
    <div className="genre-page">
      {empty || !hero ? (
        <>
          <div className="genre-head">{crumbs.props.children}</div>
          <div className="rows genre-rows">
            {all.loading && <div className="spinner" />}
            {all.error && <p className="row-empty">Couldn’t load this genre: {all.error.message}</p>}
            {empty && (
              <div className="empty-state left">
                <h3>No {heading || 'titles'} for this profile</h3>
                <p>The catalog has no titles in this genre{kind ? ` for ${section[0]}` : ''}. Try another genre from the {section[0]} page.</p>
                <div className="empty-actions" style={{ justifyContent: 'flex-start' }}><Link className="btn-white" to={section[1]}>Back to {section[0]}</Link></div>
              </div>
            )}
          </div>
        </>
      ) : (
        <>
          <Billboard t={hero} variant="full genre">{crumbs}</Billboard>
          <div className="rows overlap">
            <Row title="Your Next Watch" items={items.slice(0, 12)} />
            {byRating.length > 3 && <Row title="Critically Acclaimed" items={byRating.slice(0, 12)} />}
            {fresh.length > 0 && <Row title="New on Netflix" items={fresh} />}
            <section className="row">
              <div className="row-head"><h2 className="row-title">All {heading}</h2></div>
              <div className="title-grid">{items.map((t) => <TitleCard key={t.id} t={t} />)}</div>
            </section>
          </div>
        </>
      )}
    </div>
  )
}
