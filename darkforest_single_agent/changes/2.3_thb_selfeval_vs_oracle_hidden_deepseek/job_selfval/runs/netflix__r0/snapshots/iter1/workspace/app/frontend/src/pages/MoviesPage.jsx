import CatalogLanding from '../components/CatalogLanding.jsx'

const RAILS = [
  { key: 'action', title: 'Action & Adventure Movies', path: '/api/titles?kind=movie&genre=Action&limit=24' },
  { key: 'comedy', title: 'Comedies', path: '/api/titles?kind=movie&genre=Comedy&limit=24' },
  { key: 'scifi', title: 'Science Fiction Movies', path: '/api/titles?kind=movie&genre=Science%20Fiction&limit=24' },
  { key: 'horror', title: 'Horror Movies', path: '/api/titles?kind=movie&genre=Horror&limit=24' },
  { key: 'family', title: 'Family Movies', path: '/api/titles?kind=movie&genre=Family&limit=24' },
]

export default function MoviesPage() {
  return <CatalogLanding kind="movie" pageHeading="Movies" eyebrow="FILM" rails={RAILS} />
}
