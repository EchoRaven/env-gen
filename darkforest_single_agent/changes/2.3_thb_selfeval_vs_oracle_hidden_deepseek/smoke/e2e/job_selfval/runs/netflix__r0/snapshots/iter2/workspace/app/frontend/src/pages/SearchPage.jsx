import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api'
import Icon from '../components/Icon'
import Spinner from '../components/Spinner'
import TitleCard from '../components/TitleCard'
import TitleModal from '../components/TitleModal'

export default function SearchPage() {
  const [params] = useSearchParams()
  const query = params.get('q') || ''
  const [term, setTerm] = useState(query)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedTitle, setSelectedTitle] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    setTerm(query)
    if (!query.trim()) { setItems([]); return }
    let active = true
    setLoading(true)
    api.get(`/api/search?q=${encodeURIComponent(query)}`)
      .then((data) => { if (active) setItems(data.items || []) })
      .catch(console.error)
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [query])

  const submit = (event) => {
    event.preventDefault()
    if (term.trim()) navigate(`/search?q=${encodeURIComponent(term.trim())}`)
  }

  return (
    <div className="search-page">
      <section className="search-page-head">
        <span className="page-kicker">SEARCH</span>
        <h1>{query ? `Results for “${query}”` : 'Search the catalog'}</h1>
        <form className="big-search" onSubmit={submit}>
          <Icon name="search" size={25} />
          <input value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Titles, genres, or keywords" aria-label="Search titles" autoFocus />
          <button className="btn btn-red btn-small" type="submit">Search</button>
        </form>
      </section>
      <div className="page-content">
        {loading ? <Spinner label="Searching…" /> : items.length ? (
          <>
            <div className="results-heading"><h2>{items.length} {items.length === 1 ? 'result' : 'results'}</h2></div>
            <div className="poster-grid">
              {items.map((title) => <TitleCard key={title.id} title={title} onOpen={setSelectedTitle} onChanged={() => {}} />)}
            </div>
          </>
        ) : query ? (
          <div className="empty-state compact-empty">
            <h2>No results found for “{query}”</h2>
            <p>Try a different title, genre, or keyword.</p>
            <button className="btn btn-light" onClick={() => { setTerm(''); navigate('/browse') }}>Browse the catalog</button>
          </div>
        ) : (
          <div className="empty-state compact-empty">
            <h2>What do you want to watch?</h2>
            <p>Search by title, genre, or keyword across all 60 catalog titles.</p>
          </div>
        )}
      </div>
      {selectedTitle ? <TitleModal titleId={selectedTitle.id} initialTitle={selectedTitle} onClose={() => setSelectedTitle(null)} onChanged={() => {}} /> : null}
    </div>
  )
}
