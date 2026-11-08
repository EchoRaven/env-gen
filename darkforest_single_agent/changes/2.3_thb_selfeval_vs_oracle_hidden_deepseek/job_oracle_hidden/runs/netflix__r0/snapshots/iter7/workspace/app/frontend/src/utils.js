export function formatDuration(minutes) {
  if (!minutes) return '—'
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  if (hours > 0) return `${hours}h ${mins}m`
  return `${mins}m`
}

export function formatClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const value = Math.floor(seconds)
  const hours = Math.floor(value / 3600)
  const mins = Math.floor((value % 3600) / 60)
  const secs = String(value % 60).padStart(2, '0')
  if (hours > 0) return `${hours}:${String(mins).padStart(2, '0')}:${secs}`
  return `${mins}:${secs}`
}

export const LANGUAGES = [
  { code: 'en', name: 'English' },
  { code: 'ja', name: 'Japanese' },
  { code: 'ko', name: 'Korean' },
  { code: 'zh', name: 'Chinese' },
  { code: 'es', name: 'Spanish' },
  { code: 'fr', name: 'French' },
  { code: 'de', name: 'German' },
  { code: 'hi', name: 'Hindi' },
  { code: 'ru', name: 'Russian' },
  { code: 'af', name: 'Afrikaans' },
]

export function languageName(code) {
  return LANGUAGES.find((language) => language.code === code)?.name || code || '—'
}

export const PROFILE_COLORS = {
  red: ['#e50914', '#7a050a'],
  blue: ['#2f80ed', '#123b73'],
  yellow: ['#f5b50a', '#8c5f00'],
  green: ['#3aa76d', '#155538'],
  purple: ['#8c52ff', '#4a1d91'],
}

