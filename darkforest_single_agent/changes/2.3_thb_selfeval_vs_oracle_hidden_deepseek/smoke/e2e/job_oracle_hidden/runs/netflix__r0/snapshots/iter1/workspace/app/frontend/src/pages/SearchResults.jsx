import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { LoadingPage, ErrorState, EmptyState, PosterGrid } from '../components/PageUtilities'
import { useOpenTitle } from '../hooks'
import Icon from '../components/Icon'

export default function SearchResults() {
  const [params, setParams] = useSearchParams()
  const query = params.get('q') || ''
  const [input, setInput] = useState(query)
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(Boolean(query))
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)
  const openTitle = useOpenTitle()
  const navigate = useNavigate()

  useEffect(() => { setInput(query) }, [query])
  useEffect(() => {
    if (!query.trim()) { setResults([]); setLoading(false); return }
    setLoading(true)
    setError('')
    api(`/api/search?q=${encodeURIComponent(query.trim())}`)
      .then(setResults).catch(err => setError(err.message)).finally(() => setLoading(false))
  }, [query, nonce])

  const submit = (event) => {
    event.preventDefault()
    if (input.trim()) setParams({ q: input.trim() })
    else setParams({})
  }

  return (
    <div className="simple-catalog-page search-page">
      <div className="search-heading">
        <form className="search-page-form" onSubmit={submit}>
          <Icon name="search" size={30} />
          <input autoFocus={!query} value={input} onChange={event => setInput(event.target.value)} placeholder="Search titles or genres" aria-label="Search" />
          <button className="btn btn-red" type="submit">Search</button>
        </form>
        {query && <p>Explore titles related to: <strong>{query}</strong></p>}
      </div>
      {loading && <LoadingPage label="Searching the catalog…" />}
      {!loading && error && <ErrorState message={error} onRetry={() => setNonce(v => v + 1)} />}
      {!loading && !error && !query && (
        <EmptyState title="Search Netflix" message="Find a movie or TV show by title, genre, or synopsis." actionLabel="Browse Home" onAction={() => navigate('/browse')} />
      )}
      {!loading && !error && query && results.length === 0 && (
        <EmptyState title={`No results for “${query}”`} message="Try a different title, genre, or keyword." actionLabel="Clear search" onAction={() => { setInput(''); setParams({}); }} />
      )}
      {!loading && !error && results.length > 0 && (
        <div className="grid-wrap"><div className="language-summary"><span>{results.length} results</span></div><PosterGrid titles={results} onOpen={openTitle} /></div>
      )}
    </div>
  )
}
