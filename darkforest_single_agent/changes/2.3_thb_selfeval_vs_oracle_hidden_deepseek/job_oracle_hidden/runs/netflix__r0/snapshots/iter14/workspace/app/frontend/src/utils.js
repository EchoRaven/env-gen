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
  { code: 'ar', name: 'Arabic' },
  { code: 'da', name: 'Danish' },
  { code: 'nl', name: 'Dutch' },
  { code: 'fil', name: 'Filipino' },
  { code: 'nl-BE', name: 'Flemish' },
  { code: 'fr', name: 'French' },
  { code: 'fr-CA', name: 'French Canadian' },
  { code: 'de', name: 'German' },
  { code: 'he', name: 'Hebrew' },
  { code: 'hi', name: 'Hindi' },
  { code: 'id', name: 'Indonesian' },
  { code: 'it', name: 'Italian' },
  { code: 'ja', name: 'Japanese' },
  { code: 'ko', name: 'Korean' },
  { code: 'ms', name: 'Malay' },
  { code: 'ml', name: 'Malayalam' },
  { code: 'zh', name: 'Mandarin' },
  { code: 'no', name: 'Norwegian' },
  { code: 'pl', name: 'Polish' },
  { code: 'pt', name: 'Portuguese' },
  { code: 'ru', name: 'Russian' },
  { code: 'es', name: 'Spanish' },
  { code: 'sv', name: 'Swedish' },
  { code: 'ta', name: 'Tamil' },
  { code: 'te', name: 'Telugu' },
  { code: 'th', name: 'Thai' },
  { code: 'tr', name: 'Turkish' },
  { code: 'vi', name: 'Vietnamese' },
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

