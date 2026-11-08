import { useEffect, useMemo, useState } from 'react'
import api from '../api'
import Icon from '../components/Icon'
import Spinner from '../components/Spinner'
import TitleCard from '../components/TitleCard'
import TitleModal from '../components/TitleModal'

const LANGUAGE_NAMES = {
  en: 'English', ja: 'Japanese', zh: 'Chinese', ko: 'Korean', af: 'Afrikaans',
  es: 'Spanish', ru: 'Russian', hi: 'Hindi', de: 'German',
}

export default function BrowseByLanguagesPage() {
  const [titles, setTitles] = useState([])
  const [loading, setLoading] = useState(true)
  const [original, setOriginal] = useState('all')
  const [dubbing, setDubbing] = useState('all')
  const [subtitles, setSubtitles] = useState('all')
  const [selectedTitle, setSelectedTitle] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.get('/api/titles')
      setTitles(data.items || [])
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const languages = useMemo(() => [...new Set(titles.map((title) => title.language))].sort((a, b) => (LANGUAGE_NAMES[a] || a).localeCompare(LANGUAGE_NAMES[b] || b)), [titles])
  const filtered = useMemo(() => {
    if (dubbing !== 'all' || subtitles !== 'all') return []
    return original === 'all' ? titles : titles.filter((title) => title.language === original)
  }, [titles, original, dubbing, subtitles])

  const selectLanguage = (event, setter) => {
    setter(event.target.value)
  }

  return (
    <div className="languages-page">
      <section className="languages-header">
        <div className="languages-layout">
          <div className="languages-heading">
            <span className="sr-only">Discover</span>
            <h1>Browse by Languages</h1>
            <p>Find films and series by the language they were made in.</p>
          </div>
          <div className="language-preferences">
            <span className="preferences-title">Select Your Preferences</span>
            <div className="language-filter-rows">
              <label className="filter-row">
                <span>Original Language</span>
                <span className="select-wrap">
                  <select value={original} onChange={(event) => selectLanguage(event, setOriginal)}>
                    <option value="all">All Languages</option>
                    {languages.map((code) => <option key={code} value={code}>{LANGUAGE_NAMES[code] || code}</option>)}
                  </select>
                  <Icon name="chevronDown" size={15} />
                </span>
              </label>
              <label className="filter-row">
                <span>Dubbing</span>
                <span className="select-wrap">
                  <select value={dubbing} onChange={(event) => selectLanguage(event, setDubbing)}>
                    <option value="all">All Languages</option>
                    {languages.map((code) => <option key={code} value={code}>{LANGUAGE_NAMES[code] || code}</option>)}
                  </select>
                  <Icon name="chevronDown" size={15} />
                </span>
              </label>
              <label className="filter-row">
                <span>Subtitles</span>
                <span className="select-wrap">
                  <select value={subtitles} onChange={(event) => selectLanguage(event, setSubtitles)}>
                    <option value="all">All Languages</option>
                    {languages.map((code) => <option key={code} value={code}>{LANGUAGE_NAMES[code] || code}</option>)}
                  </select>
                  <Icon name="chevronDown" size={15} />
                </span>
              </label>
            </div>
          </div>
        </div>
      </section>
      <div className="page-content languages-content">
        {dubbing !== 'all' || subtitles !== 'all' ? (
          <div className="honest-notice">
            <strong>No {dubbing !== 'all' ? 'dubbing' : 'subtitle'} metadata is present for this catalog.</strong>
            <span>The provided dataset supplies original language only. Choose “All Languages” to continue browsing.</span>
          </div>
        ) : null}
        <div className="results-heading">
          <h2>{original === 'all' ? 'All Titles' : `${LANGUAGE_NAMES[original] || original} Titles`}</h2>
          <span>{filtered.length} {filtered.length === 1 ? 'title' : 'titles'}</span>
        </div>
        {loading ? <Spinner label="Loading titles…" /> : filtered.length ? (
          <div className="poster-grid">
            {filtered.map((title) => <TitleCard key={title.id} title={title} onOpen={setSelectedTitle} onChanged={load} />)}
          </div>
        ) : (
          <div className="empty-state compact-empty">
            <h2>No titles match these filters</h2>
            <p>Reset the language filters to see the full catalog.</p>
            <button className="btn btn-light" onClick={() => { setOriginal('all'); setDubbing('all'); setSubtitles('all') }}>Reset filters</button>
          </div>
        )}
      </div>
      {selectedTitle ? <TitleModal titleId={selectedTitle.id} initialTitle={selectedTitle} onClose={() => setSelectedTitle(null)} onChanged={load} /> : null}
    </div>
  )
}
