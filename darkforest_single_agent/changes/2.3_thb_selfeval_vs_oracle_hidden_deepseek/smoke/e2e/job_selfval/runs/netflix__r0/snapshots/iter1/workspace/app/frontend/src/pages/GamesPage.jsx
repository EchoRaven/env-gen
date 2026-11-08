import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import Spinner from '../components/Spinner'
import TitleModal from '../components/TitleModal'
import TitleRail from '../components/TitleRail'

export default function GamesPage() {
  const [allTitles, setAllTitles] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedTitle, setSelectedTitle] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    api.get('/api/titles')
      .then((data) => setAllTitles(data.items || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const family = allTitles.filter((title) => (title.genres || []).some((genre) => ['Family', 'Comedy', 'Animation', 'Adventure'].includes(genre)))

  if (loading) return <div className="page-loading"><Spinner label="Loading games…" /></div>

  return (
    <div className="games-page">
      <section className="games-hero">
        <div className="games-art" aria-hidden="true">
          {['tv_66732', 'movie_1368337', 'tv_37854', 'movie_1275779'].map((name) => (
            <span key={name} style={{ backgroundImage: `url(/assets/backdrops/${name}.jpg)` }} />
          ))}
        </div>
        <div className="games-hero-shade" />
        <div className="games-hero-copy">
          <div className="hero-badge"><span className="n-mini">N</span>NETFLIX GAMES</div>
          <h1>Games</h1>
          <p>No games are included in the current catalog. This honest empty state keeps the catalog free of invented titles.</p>
          <div className="hero-actions">
            <button className="btn btn-light" onClick={() => navigate('/shows')}>Explore TV Shows</button>
            <button className="btn btn-more" onClick={() => navigate('/movies')}>Explore Movies</button>
          </div>
        </div>
      </section>
      <div className="page-content">
        <TitleRail title="Party Games" items={[]} emptyMessage="No game titles are available in the provided dataset." onChanged={() => {}} />
        <TitleRail title="From the catalog" eyebrow="WHILE YOU WAIT" items={family.slice(0, 18)} onOpen={setSelectedTitle} onChanged={() => {}} />
        <TitleRail title="Family Movie Night" items={allTitles.filter((title) => title.kind === 'movie' && (title.genres || []).includes('Family')).slice(0, 18)} onOpen={setSelectedTitle} onChanged={() => {}} />
      </div>
      {selectedTitle ? <TitleModal titleId={selectedTitle.id} initialTitle={selectedTitle} onClose={() => setSelectedTitle(null)} onChanged={() => {}} /> : null}
    </div>
  )
}
