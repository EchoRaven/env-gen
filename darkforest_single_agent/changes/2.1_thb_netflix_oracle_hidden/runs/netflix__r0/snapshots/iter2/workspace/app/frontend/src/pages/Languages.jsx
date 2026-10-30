import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import TitleCard from '../components/TitleCard';
import { API } from '../api';
import { useApi } from '../hooks';
import { LANGUAGES } from '../utils';

const MODES = [['original', 'Original Language'], ['dubbing', 'Dubbing'], ['subtitles', 'Subtitles']];

function Dropdown({ label, value, options, onChange, wide }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);
  const current = options.find(([v]) => v === value);
  return (
    <div className={`lang-dd ${wide ? 'wide' : ''}`} ref={ref}>
      <button className="lang-dd-btn" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open} aria-label={label}>
        {current ? current[1] : '—'} <span className="tri" />
      </button>
      {open && (
        <ul className="lang-dd-menu" role="listbox">
          {options.map(([v, l]) => (
            <li key={v}><button role="option" aria-selected={v === value} onClick={() => { onChange(v); setOpen(false); }}>{l}</button></li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Languages() {
  const [params, setParams] = useSearchParams();
  const mode = params.get('mode') || 'original';
  const lang = params.get('lang') || 'en';
  const [all] = useApi(() => API.titles({ limit: 500 }));
  const langs = useMemo(() => {
    const codes = [...new Set((all || []).map((t) => t.language).filter(Boolean))];
    return codes.map((c) => [c, LANGUAGES[c] || c]).sort((a, b) => a[1].localeCompare(b[1]));
  }, [all]);
  const [titles] = useApi(() => (mode === 'original' ? API.titles({ language: lang, limit: 500 }) : Promise.resolve([])), [mode, lang]);
  const set = (k, v) => setParams((p) => { p.set(k, v); return p; });
  return (
    <div className="page grid-page languages">
      <div className="lang-head">
        <h1 className="page-title">Browse by Languages</h1>
        <div className="lang-prefs">
          <span>Select Your Preferences</span>
          <Dropdown label="Language preference type" value={mode} options={MODES} onChange={(v) => set('mode', v)} />
          <Dropdown label="Language" value={lang} options={langs.length ? langs : [['en', 'English']]} onChange={(v) => set('lang', v)} wide />
        </div>
      </div>
      {titles === null && <div className="spinner" />}
      {titles && titles.length === 0 && (
        <div className="empty-state">
          <p>
            {mode === 'original'
              ? `No titles in ${LANGUAGES[lang] || lang} for this profile.`
              : `The catalog has no ${mode === 'dubbing' ? 'dubbing' : 'subtitle'} track information, so no titles can be listed for ${LANGUAGES[lang] || lang} ${mode}. Try “Original Language”.`}
          </p>
        </div>
      )}
      {titles && titles.length > 0 && (
        <div className="title-grid">{titles.map((t) => <TitleCard key={t.id} title={t} />)}</div>
      )}
    </div>
  );
}
