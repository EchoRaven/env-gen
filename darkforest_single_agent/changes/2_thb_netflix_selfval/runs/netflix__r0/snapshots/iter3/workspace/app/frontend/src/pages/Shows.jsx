import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import Billboard from '../components/Billboard.jsx'
import Row from '../components/Row.jsx'
import GenreRow from '../components/GenreRow.jsx'
import GenresMenu from '../components/GenresMenu.jsx'
import { rail } from './BrowseHome.jsx'

export function SectionLanding({ kind, heading, picksTitle, picks }) {
  const { profileId } = useSession()
  const trending = useAsync(() => api.trending({ kind, limit: 20 }), [kind, profileId])
  const top = useAsync(() => api.top10({ kind }), [kind, profileId])
  const fresh = useAsync(() => api.titles({ kind, sort: 'new', limit: 20 }), [kind, profileId])
  const pickRail = useAsync(picks, [kind, profileId])
  const genres = useAsync(() => api.genres({ kind }), [kind, profileId])
  const hero = trending.data?.items?.[0]
  return (
    <div className="browse">
      <Billboard t={hero} variant="full">
        <div className="section-head">
          <h1>{heading}</h1>
          <GenresMenu kind={kind} />
        </div>
      </Billboard>
      <div className="rows overlap">
        <Row title={picksTitle} {...rail(pickRail)} />
        <Row title="Trending Now" {...rail(trending)} />
        <Row title={`Top 10 ${kind === 'series' ? 'TV Shows' : 'Movies'} Today`} {...rail(top)} ranked />
        <Row title="New on Netflix" {...rail(fresh)} />
        {(genres.data?.items || []).filter((g) => g.title_count >= 3).map((g) => (
          <GenreRow key={g.id} genre={g} kind={kind} label={kind === 'series' ? `TV ${g.name}` : `${g.name} Movies`} />
        ))}
      </div>
    </div>
  )
}

export default function Shows() {
  return <SectionLanding kind="series" heading="TV Shows" picksTitle="Today's Top Picks for You"
    picks={() => api.titles({ kind: 'series', sort: 'rating', limit: 20 })} />
}
