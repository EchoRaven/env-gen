import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import Billboard from '../components/Billboard.jsx'
import Row from '../components/Row.jsx'
import GenreRow from '../components/GenreRow.jsx'

export default function BrowseHome() {
  const { profile, profileId, listVersion } = useSession()
  const trending = useAsync(() => api.trending({ limit: 20 }), [profileId])
  const cw = useAsync(() => api.continueWatching(), [profileId])
  const top = useAsync(() => api.top10({ kind: 'series' }), [profileId])
  const list = useAsync(() => api.myList(), [profileId, listVersion])
  const fresh = useAsync(() => api.titles({ sort: 'new', limit: 20 }), [profileId])
  const genres = useAsync(() => api.genres(), [profileId])
  const hero = trending.data?.items?.find((t) => t.kind === 'series') || trending.data?.items?.[0]
  const g = (name) => genres.data?.items?.find((x) => x.name === name)

  return (
    <div className="browse">
      <div className="inset-wrap"><Billboard t={hero} variant="inset" /></div>
      <div className="rows">
        {cw.data?.items?.length > 0 && <Row title={`Continue Watching for ${profile?.name || 'you'}`} {...rail(cw)} />}
        <Row title="Trending Now" {...rail(trending)} size="lg" />
        <GenreRow genre={g('Action & Adventure')} kind="series" label="TV Action & Adventure" />
        <Row title="Top 10 TV Shows Today" {...rail(top)} ranked />
        <Row title="My List" {...rail(list)} />
        <Row title="New on Netflix" {...rail(fresh)} />
        <GenreRow genre={g('Comedy')} label="Comedies" />
        <GenreRow genre={g('Sci-Fi & Fantasy')} kind="series" label="Sci-Fi & Fantasy TV" />
        <GenreRow genre={g('Animation')} label="Animation" />
        <GenreRow genre={g('Horror')} kind="movie" label="Horror Movies" />
        <GenreRow genre={g('Drama')} label="Dramas" />
      </div>
    </div>
  )
}

export const rail = (s) => ({ items: s.data?.items, loading: s.loading, error: s.error })
