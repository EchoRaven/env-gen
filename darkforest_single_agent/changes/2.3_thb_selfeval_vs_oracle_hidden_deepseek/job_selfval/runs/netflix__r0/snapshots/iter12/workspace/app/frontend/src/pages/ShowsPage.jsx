import CatalogLanding from '../components/CatalogLanding.jsx'

const RAILS = [
  { key: 'drama', title: 'TV Dramas', path: '/api/titles?kind=series&genre=Drama&limit=24' },
  { key: 'comedy', title: 'TV Comedies', path: '/api/titles?kind=series&genre=Comedy&limit=24' },
  { key: 'action', title: 'TV Action & Adventure', path: '/api/titles?kind=series&genre=Action%20%26%20Adventure&limit=24' },
  { key: 'scifi', title: 'Sci-Fi & Fantasy TV Shows', path: '/api/titles?kind=series&genre=Sci-Fi%20%26%20Fantasy&limit=24' },
  { key: 'crime', title: 'Crime TV Shows', path: '/api/titles?kind=series&genre=Crime&limit=24' },
]

export default function ShowsPage() {
  return <CatalogLanding kind="series" pageHeading="TV Shows" eyebrow="SERIES" rails={RAILS} featuredId={28} />
}
