import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import PosterGrid from '../components/PosterGrid.jsx'
import Icon from '../components/Icon.jsx'
import { useTitleOverlay } from '../components/useTitleOverlay.js'

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const query = params.get('q') || ''
  const { api } = useAuth()
  const { openTitle } = useTitleOverlay()
  const [input, setInput] = useState(query)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { setInput(query) }, [query])

  useEffect(() => {
    let cancelled = false
    if (!query.trim()) {
      setItems([])
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    api.get(`/api/search?q=${encodeURIComponent(query.trim())}`).then((result) => {
      if (!cancelled) setItems(result.items || [])
    }).catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [api, query])

  function submit(event) {
    event.preventDefault()
    const next = input.trim()
    if (next) setParams({ q: next })
  }

  return (
    <PageShell className="browse-app search-page">
      <div className="browse-main">
        <div className="search-page-header">
          <h1>{query ? `Search results for “${query}”` : 'Search'}</h1>
          <form className="search-page-form" onSubmit={submit}>
            <Icon name="search" size={22} />
            <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Titles, genres, or synopsis" aria-label="Search the catalog" autoFocus={!query} />
            <button type="submit" className="btn btn-red btn-small">Search</button>
          </form>
        </div>
        {loading && <div className="page-loading">Searching the catalog…</div>}
        {error && <div className="page-error">{error}</div>}
        {!loading && query && !error && (
          <PosterGrid
            items={items}
            onOpen={openTitle}
            emptyTitle="No matches found"
            emptyText={`Your search for “${query}” did not have any matches. Try another title or genre.`}
          />
        )}
        {!query && <div className="search-prompt">Find your next watch by title, genre, or synopsis.</div>}
      </div>
    </PageShell>
  )
}
