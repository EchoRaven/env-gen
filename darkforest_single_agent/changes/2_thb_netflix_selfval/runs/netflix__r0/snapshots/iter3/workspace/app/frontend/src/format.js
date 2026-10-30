export const LANGUAGES = {
  en: 'English', ja: 'Japanese', zh: 'Mandarin', ko: 'Korean', af: 'Afrikaans', es: 'Spanish',
  ru: 'Russian', hi: 'Hindi', de: 'German', fr: 'French', it: 'Italian', pt: 'Portuguese',
}
export const languageName = (code) => LANGUAGES[code] || (code ? code.toUpperCase() : '—')

export const CURRENT_YEAR = '2026'

export function lengthLabel(t) {
  if (!t) return ''
  if (t.kind === 'series') {
    if (t.seasons > 1) return `${t.seasons} Seasons`
    if (t.episode_count) return `${t.episode_count} Episodes`
    return 'Limited Series'
  }
  return 'Movie'
}

// Durations are the real lengths of the attached clips (seconds).
export function clipLength(sec) {
  if (sec == null) return ''
  const s = Math.round(sec)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m ${s % 60}s`
}

export function timecode(sec) {
  if (!isFinite(sec) || sec < 0) sec = 0
  const s = Math.floor(sec % 60).toString().padStart(2, '0')
  const m = Math.floor(sec / 60) % 60
  const h = Math.floor(sec / 3600)
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export const genreNames = (t, n = 3) => (t && t.genres ? t.genres.slice(0, n).map((g) => g.name) : [])

export const isNew = (t) => t && t.year === CURRENT_YEAR
