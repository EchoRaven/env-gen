import { useMemo, useState } from 'react'
import Header from '../components/Header'
import { useFetch } from '../lib/hooks'
import { mediaUrl } from '../lib/util'
import { openTitleModal } from '../lib/modalStore'

const LANG_NAMES = {
  en: 'English', ja: 'Japanese', zh: 'Mandarin', ko: 'Korean', af: 'Afrikaans',
  es: 'Spanish', ru: 'Russian', hi: 'Hindi', de: 'German',
}

export default function LanguagesPage() {
  const { data: titles, loading } = useFetch('/api/titles')
  const [orig, setOrig] = useState('all')
  const [dub, setDub] = useState('all')
  const [sub, setSub] = useState('all')

  const languages = useMemo(() => {
    const set = new Set()
    for (const t of titles || []) if (t.language) set.add(t.language)
    return Array.from(set).sort()
  }, [titles])

  // No dubbing/subtitle metadata exists in this catalog — only Original Language has real data.
  const filtered = useMemo(() => {
    if (dub !== 'all' || sub !== 'all') return []
    return (titles || []).filter((t) => orig === 'all' || t.language === orig)
  }, [titles, orig, dub, sub])

  if (loading) return <div className="grid-page"><h1>Browse by Languages</h1><p style={{ color: '#808080' }}>Loading…</p></div>

  return (
    <div className="grid-page">
      <Header />
      <h1>Browse by Languages</h1>
      <div className="lang-panels">
        <div className="lang-panel">
          <h3>Original Language</h3>
          <div className="lp-sub">Select the language a title was originally produced in.</div>
          <select className="filter-select" value={orig} onChange={(e) => setOrig(e.target.value)} aria-label="Original language">
            <option value="all">All original languages</option>
            {languages.map((l) => (
              <option key={l} value={l}>{LANG_NAMES[l] || l}</option>
            ))}
          </select>
        </div>
        <div className="lang-panel">
          <h3>Dubbing</h3>
          <div className="lp-sub">Select the language a title is dubbed in.</div>
          <select className="filter-select" value={dub} onChange={(e) => setDub(e.target.value)} aria-label="Dubbing language">
            <option value="all">All dubbed languages</option>
          </select>
          {dub !== 'all' && <div className="rail-empty">No dubbed titles available in this catalog.</div>}
        </div>
        <div className="lang-panel">
          <h3>Subtitles</h3>
          <div className="lp-sub">Select the language a title has subtitles in.</div>
          <select className="filter-select" value={sub} onChange={(e) => setSub(e.target.value)} aria-label="Subtitle language">
            <option value="all">All subtitle languages</option>
          </select>
          {sub !== 'all' && <div className="rail-empty">No subtitled titles available in this catalog.</div>}
        </div>
      </div>
      {(dub !== 'all' || sub !== 'all') ? (
        <div style={{ color: '#808080', fontSize: 1.05, padding: '20px 0' }}>
          This catalog only records each title’s original language, so no titles match the dubbing/subtitles filter.
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ color: '#808080', fontSize: 1.05, padding: '20px 0' }}>No titles in this language.</div>
      ) : (
        <div className="poster-grid">
          {filtered.map((t) => (
            <div key={t.id} className="card grid-card" onClick={() => openTitleModal(t.id)}>
              <img className="card-poster" src={mediaUrl(t.poster)} alt={t.name} loading="lazy" />
              <div className="card-name">{t.name}</div>
              <div style={{ fontSize: 0.75, color: '#a3a3a3', padding: '0 2px' }}>
                {t.year} · {LANG_NAMES[t.language] || t.language || '—'}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
