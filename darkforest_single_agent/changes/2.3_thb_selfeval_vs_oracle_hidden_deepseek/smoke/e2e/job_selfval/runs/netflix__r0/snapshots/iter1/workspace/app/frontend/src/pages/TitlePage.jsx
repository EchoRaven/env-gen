import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import api from '../api'
import Header from '../components/Header'
import Spinner from '../components/Spinner'
import TitleModal from '../components/TitleModal'

export default function TitlePage() {
  const { titleId } = useParams()
  const [title, setTitle] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const load = async () => {
    try {
      const data = await api.get(`/api/titles/${titleId}`)
      setTitle(data.item)
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [titleId]) // eslint-disable-line react-hooks/exhaustive-deps

  const close = () => {
    if (window.history.length > 1) navigate(-1)
    else navigate('/browse')
  }

  return (
    <div className="title-page">
      <Header />
      <div className="title-page-bg" style={title ? { '--bg': `url(${title.backdrop || title.poster})` } : undefined} />
      <div className="title-page-shade" />
      {loading ? <div className="page-loading"><Spinner label="Loading title…" /></div> : null}
      {error ? <div className="page-loading"><p>{error}</p><Link className="btn btn-light" to="/browse">Back to browse</Link></div> : null}
      {title ? <TitleModal titleId={title.id} initialTitle={title} onClose={close} onChanged={load} /> : null}
    </div>
  )
}
