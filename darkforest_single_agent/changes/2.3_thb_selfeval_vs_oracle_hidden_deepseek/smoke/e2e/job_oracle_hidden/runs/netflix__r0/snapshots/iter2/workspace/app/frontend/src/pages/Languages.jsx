import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { LoadingPage, ErrorState, EmptyState, PosterGrid } from '../components/PageUtilities'
import { useOpenTitle } from '../hooks'

const languageNames = {
  en: 'English', ja: 'Japanese', zh: 'Chinese', ko: 'Korean', af: 'Afrikaans',
  es: 'Spanish', ru: 'Russian', hi: 'Hindi', de: 'German',
}

const tabs = [
  ['original', 'Original Language'],
  ['dubbing', 'Dubbing'],
  ['subtitles', 'Subtitles'],
]

export default function Languages() {
  const [titles, setTitles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('original')
  const [language, setLanguage] = useState('all')
  const [nonce, setNonce] = useState(0)
  const openTitle = useOpenTitle()

  useEffect(() => {
    setLoading(true)
    api('/api/titles?limit=60')
      .then(setTitles).catch(err => setError(err.message)).finally(() => setLoading(false))
  }, [nonce])

  const languages = useMemo(() => {
    const codes = [...new Set(titles.map(item => item.language).filter(Boolean))].sort()
    return codes.map(code => [code, languageNames[code] || code.toUpperCase()])
  }, [titles])

  const filtered = language === 'all' ? titles : titles.filter(item => item.language === language)

  return (
    <div className="languages-page">
      <div className="languages-hero">
        <h1>Browse by Languages</h1>
        <div className="language-preferences">
          <h2>Select Your Preferences</h2>
          <div className={`preference-row ${tab === 'original' ? 'active' : ''}`}>
            <button type="button" className="preference-label" onClick={() => setTab('original')}>Original Language</button>
            <select value={language} onChange={event => setLanguage(event.target.value)} aria-label="Original language">
              <option value="all">All Languages</option>
              {languages.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          </div>
          <div className={`preference-row ${tab === 'dubbing' ? 'active' : ''}`}>
            <button type="button" className="preference-label" onClick={() => setTab('dubbing')}>Dubbing</button>
            <span className="preference-unavailable">Not available</span>
          </div>
          <div className={`preference-row ${tab === 'subtitles' ? 'active' : ''}`}>
            <button type="button" className="preference-label" onClick={() => setTab('subtitles')}>Subtitles</button>
            <span className="preference-unavailable">Not available</span>
          </div>
        </div>
      </div>
      <main className="languages-main">
        {loading && <LoadingPage label="Loading languages…" />}
        {!loading && error && <ErrorState message={error} onRetry={() => setNonce(v => v + 1)} />}
        {!loading && !error && tab !== 'original' && (
          <EmptyState
            title={`${tab === 'dubbing' ? 'Dubbing' : 'Subtitles'} information is unavailable`}
            message="The supplied catalog includes original-language metadata only, so this view shows an honest empty state rather than invented availability."
            actionLabel="Browse Original Language"
            onAction={() => { setTab('original'); setLanguage('all') }}
          />
        )}
        {!loading && !error && tab === 'original' && (
          <>
            <div className="language-summary"><span>{filtered.length} titles</span><span>{language === 'all' ? 'All original languages' : languageNames[language] || language}</span></div>
            <PosterGrid titles={filtered} onOpen={openTitle} emptyTitle="No titles in this language" emptyMessage="Try selecting another language." />
          </>
        )}
      </main>
    </div>
  )
}
