import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import Rail from '../components/Rail'
import Icon from '../components/Icon'
import { useFetch } from '../lib/hooks'

export default function Games() {
  const nav = useNavigate()
  const { loading } = useFetch('/api/titles')
  if (loading) return <div className="page-pad" style={{ minHeight: '100vh' }} />

  return (
    <div style={{ minHeight: '100vh' }}>
      <Header />
      <div
        style={{
          height: '52vh', minHeight: 340, position: 'relative', display: 'flex', alignItems: 'flex-end',
          background: 'linear-gradient(120deg, #101014 0%, #1c1c24 55%, #141414 100%)',
        }}
      >
        <div className="hero-content" style={{ padding: '0 4vw 70px' }}>
          <h1 className="hero-title">Games</h1>
          <p className="hero-synopsis" style={{ marginBottom: 0 }}>
            Play the latest titles on Netflix Games. This catalog doesn’t include games yet — the rails below will fill in as titles are added.
          </p>
        </div>
      </div>
      <div style={{ marginTop: 10, position: 'relative', zIndex: 5, padding: '10px 0 40px' }}>
        <Rail title="Party Games" items={[]} emptyText="No party games available yet — check back soon." />
        <Rail title="Action Games" items={[]} emptyText="No action games available yet." />
        <Rail title="Puzzle Games" items={[]} emptyText="No puzzle games available yet." />
        <div style={{ padding: '0 4vw', color: '#808080', fontSize: 0.9 }}>
          Looking for something to watch instead? <a href="#/browse" onClick={(e) => { e.preventDefault(); nav('/browse') }} style={{ color: '#e5e5e5', textDecoration: 'underline' }}>Browse all titles</a>
        </div>
      </div>
    </div>
  )
}
