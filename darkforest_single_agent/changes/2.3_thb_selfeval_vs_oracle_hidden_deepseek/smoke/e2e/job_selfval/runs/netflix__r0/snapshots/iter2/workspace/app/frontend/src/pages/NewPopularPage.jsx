import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import Spinner from '../components/Spinner'
import TitleModal from '../components/TitleModal'
import TitleRail from '../components/TitleRail'

export default function NewPopularPage() {
  const [seriesTop, setSeriesTop] = useState([])
  const [movieTop, setMovieTop] = useState([])
  const [newTitles, setNewTitles] = useState([])
  const [coming, setComing] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedTitle, setSelectedTitle] = useState(null)
  const navigate = useNavigate()

  const load = async () => {
    try {
      const [seriesData, movieData, allData] = await Promise.all([
        api.get('/api/titles/top10?kind=series'),
        api.get('/api/titles/top10?kind=movie'),
        api.get('/api/titles?sort=newest'),
      ])
      setSeriesTop(seriesData.items || [])
      setMovieTop(movieData.items || [])
      const all = allData.items || []
      setNewTitles(all.slice(0, 20))
      setComing(all.filter((title) => title.year >= 2026).slice(0, 18))
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  if (loading) return <div className="page-loading"><Spinner label="Loading new and popular…" /></div>

  return (
    <div className="new-page">
      <div className="page-content new-content">
        <h1 className="sr-only">New &amp; Popular</h1>
        <div className="new-content-head">
          <span className="page-kicker">NEW &amp; POPULAR</span>
          <button className="btn btn-outline btn-small" onClick={() => navigate('/browse/languages')}>Browse by Languages</button>
        </div>
        <TitleRail title="New on Netflix" items={newTitles} onOpen={setSelectedTitle} onChanged={load} />
        <TitleRail title="Top 10 TV Shows" eyebrow="TODAY" items={seriesTop} top10 onOpen={setSelectedTitle} onChanged={load} />
        <TitleRail title="Top 10 Movies" eyebrow="TODAY" items={movieTop} top10 onOpen={setSelectedTitle} onChanged={load} />
        <TitleRail title="Coming This Week" items={coming} onOpen={setSelectedTitle} onChanged={load} />
        <section className="coming-panel">
          <div>
            <span className="page-kicker">COMING SOON</span>
            <h2>Your next obsession is almost here.</h2>
            <p>New seasons, new stories, and new reasons to stay in.</p>
          </div>
          <button className="btn btn-light" onClick={() => setSelectedTitle(coming[0] || newTitles[0])} disabled={!coming.length && !newTitles.length}>
            See what’s coming
          </button>
        </section>
      </div>
      {selectedTitle ? <TitleModal titleId={selectedTitle.id} initialTitle={selectedTitle} onClose={() => setSelectedTitle(null)} onChanged={load} /> : null}
    </div>
  )
}
