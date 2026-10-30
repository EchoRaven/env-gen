import { api } from '../api.js'
import { SectionLanding } from './Shows.jsx'

export default function Movies() {
  return <SectionLanding kind="movie" heading="Movies" picksTitle="Gems for You"
    picks={() => api.titles({ kind: 'movie', sort: 'rating', limit: 20 })} />
}
