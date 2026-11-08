import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import PosterGrid from '../components/PosterGrid.jsx'
import { useTitleOverlay } from '../components/useTitleOverlay.js'

const LANGUAGE_LABELS = {
  en: 'English', ja: 'Japanese', zh: 'Chinese', ko: 'Korean', af: 'Afrikaans',
  es: 'Spanish', ru: 'Russian', hi: 'Hindi', de: 'German',
}

export default function BrowseByLanguagesPage() {
  const [params, setParams] = useSearchParams()
  const { api } = useAuth()
  const { openTitle } = useTitleOverlay()
  const [titles, setTitles] = useState([])
  const [selected, setSelected] = useState(params.get('language') || 'all')
  const [track, setTrack] = useState('original')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    const query = selected === 'all' ? '' : `&language=${encodeURIComponent(selected)}`
    api.get(`/api/titles?limit=200${query}`).then((result) => {
      if (!cancelled) setTitles(result.items || [])
    }).catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [api, selected])

  const languages = useMemo(() => {
    const found = new Map()
    // The full catalog is fetched below; language labels come from the shared mapping.
    Object.entries(LANGUAGE_LABELS).forEach(([code, name]) => found.set(name, code))
    return [...found.keys()].sort()
  }, [])

  function change(value) {
    setSelected(value)
    if (value === 'all') setParams({})
    else setParams({ language: value })
  }

  return (
    <PageShell className="browse-app languages-page">
      <div className="browse-main">
        <h1 className="languages-title">Browse by Languages</h1>
        <div className="language-controls">
          <label>
            <span>Original Language</span>
            <select value={selected} onChange={(event) => { setTrack('original'); change(event.target.value) }}>
              <option value="all">All languages</option>
              {languages.map((language) => <option key={language} value={language}>{language}</option>)}
            </select>
          </label>
          <label>
            <span>Dubbing</span>
            <select value={selected} onChange={(event) => { setTrack('dubbing'); change(event.target.value) }}>
              <option value="all">All languages</option>
              {languages.map((language) => <option key={language} value={language}>{language}</option>)}
            </select>
          </label>
          <label>
            <span>Subtitles</span>
            <select value={selected} onChange={(event) => { setTrack('subtitles'); change(event.target.value) }}>
              <option value="all">All languages</option>
              {languages.map((language) => <option key={language} value={language}>{language}</option>)}
            </select>
          </label>
        </div>
        <p className="language-note">
          {track === 'original'
            ? 'Showing titles whose original language matches the selected language.'
            : 'This catalog stores original-language metadata only, so the selected language filters the real catalog; dubbed or subtitle tracks are not represented in the dataset.'}
        </p>
        {loading && <div className="page-loading">Loading titles…</div>}
        {error && <div className="page-error">{error}</div>}
        {!loading && !error && (
          <PosterGrid items={titles} onOpen={openTitle} emptyTitle="No titles in this language" emptyText="Try a different language or browse the full catalog." />
        )}
      </div>
    </PageShell>
  )
}
