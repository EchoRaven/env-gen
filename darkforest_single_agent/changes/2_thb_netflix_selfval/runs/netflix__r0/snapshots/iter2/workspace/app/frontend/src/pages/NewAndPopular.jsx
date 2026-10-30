import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import Row from '../components/Row.jsx'
import { rail } from './BrowseHome.jsx'

export default function NewAndPopular() {
  const { profileId } = useSession()
  const fresh = useAsync(() => api.titles({ year: '2026', limit: 30 }), [profileId])
  const topTv = useAsync(() => api.top10({ kind: 'series' }), [profileId])
  const topMovies = useAsync(() => api.top10({ kind: 'movie' }), [profileId])
  const trending = useAsync(() => api.trending({ limit: 20 }), [profileId])
  return (
    <div className="browse plain">
      <div className="rows top-pad">
        <Row title="New on Netflix" {...rail(fresh)} emptyText="No new releases right now." />
        <Row title="Top 10 TV Shows Today" {...rail(topTv)} ranked emptyText="No ranked shows for this profile." />
        <Row title="Top 10 Movies Today" {...rail(topMovies)} ranked emptyText="No ranked movies for this profile." />
        <Row title="Worth the Wait" {...rail(trending)} />
        <Row title="Coming This Week" items={[]} emptyText="Nothing new is scheduled to arrive this week." />
      </div>
    </div>
  )
}
