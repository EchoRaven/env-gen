import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'
import { CaretDown } from '../icons.jsx'
import { languageName } from '../format.js'
import TitleCard from '../components/TitleCard.jsx'

function Dropdown({ value, options, onChange, label, wide }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const current = options.find((o) => o.value === value)
  return (
    <div className={`lang-dd ${wide ? 'wide' : ''}`} ref={ref}>
      <button className="lang-dd-btn" aria-label={label} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span>{current ? current.label : '—'}</span> <CaretDown size={12} />
      </button>
      {open && (
        <ul className="lang-dd-list" role="listbox">
          {options.map((o) => (
            <li key={o.value}>
              <button className={o.value === value ? 'on' : ''} onClick={() => { onChange(o.value); setOpen(false) }}>
                {o.label}{o.count != null ? <small> ({o.count})</small> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const MODES = [
  { value: 'original', label: 'Original Language' },
  { value: 'dubbing', label: 'Dubbing' },
  { value: 'subtitles', label: 'Subtitles' },
]
const SORTS = [
  { value: 'popular', label: 'Suggestions For You' },
  { value: 'new', label: 'Year Released' },
  { value: 'az', label: 'A-Z' },
  { value: 'za', label: 'Z-A' },
]

export default function BrowseByLanguages() {
  const { profileId } = useSession()
  const [params, setParams] = useSearchParams()
  const mode = params.get('mode') || 'original'
  const lang = params.get('lang') || 'en'
  const sort = params.get('sort') || 'popular'
  const set = (k, v) => { const p = new URLSearchParams(params); p.set(k, v); p.delete('title'); setParams(p) }
  const langs = useAsync(() => api.languages(), [profileId])
  const titles = useAsync(
    () => (mode === 'original' ? api.titles({ language: lang, sort, limit: 200 }) : Promise.resolve({ items: [] })),
    [mode, lang, sort, profileId]
  )
  const langOptions = (langs.data?.items || [])
    .map((l) => ({ value: l.code, label: languageName(l.code), count: l.title_count }))
    .sort((a, b) => a.label.localeCompare(b.label))
  const items = titles.data?.items || []

  return (
    <div className="grid-page lang-page">
      <div className="lang-head">
        <h1 className="page-title">Browse by Languages</h1>
        <div className="lang-prefs">
          <span>Select Your Preferences</span>
          <Dropdown label="Language preference" value={mode} options={MODES} onChange={(v) => set('mode', v)} />
          <Dropdown label="Language" value={lang} options={langOptions} onChange={(v) => set('lang', v)} />
          <span>Sort by</span>
          <Dropdown label="Sort by" value={sort} options={SORTS} onChange={(v) => set('sort', v)} />
        </div>
      </div>
      {mode !== 'original' && (
        <div className="empty-state left">
          <h3>No {mode === 'dubbing' ? 'dubbed audio' : 'subtitle'} tracks in this catalog</h3>
          <p>The titles here only carry their original-language audio. Switch to <b>Original Language</b> to browse them.</p>
        </div>
      )}
      {mode === 'original' && titles.loading && <div className="spinner" />}
      {mode === 'original' && !titles.loading && items.length === 0 && (
        <div className="empty-state left"><p>No titles in {languageName(lang)} for this profile.</p></div>
      )}
      <div className="title-grid">{items.map((t) => <TitleCard key={t.id} t={t} />)}</div>
    </div>
  )
}
