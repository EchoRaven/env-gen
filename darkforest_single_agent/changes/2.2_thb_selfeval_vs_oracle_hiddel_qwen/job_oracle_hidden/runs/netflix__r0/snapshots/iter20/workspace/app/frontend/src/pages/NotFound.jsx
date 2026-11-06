import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'

export default function NotFound() {
  const nav = useNavigate()
  return (
    <div className="grid-page" style={{ minHeight: '100vh' }}>
      <Header />
      <h1 style={{ fontSize: 3 }}>Oops!</h1>
      <p style={{ color: '#a3a3a3' }}>We couldn’t find that page. It may have been removed or the link is broken.</p>
      <button className="btn btn-red" style={{ padding: '10px 22px' }} onClick={() => nav('/browse')}>Back to Home</button>
    </div>
  )
}
