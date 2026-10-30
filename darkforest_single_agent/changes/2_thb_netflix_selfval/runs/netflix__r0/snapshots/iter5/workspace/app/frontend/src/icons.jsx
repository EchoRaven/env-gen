import play from './icons/play.svg?raw'
import plus from './icons/plus.svg?raw'
import search from './icons/search.svg?raw'
import bell from './icons/bell.svg?raw'
import close from './icons/close.svg?raw'
import thumbsUp from './icons/thumbs_up.svg?raw'
import thumbsDown from './icons/thumbs_down.svg?raw'
import thumbsUpTwo from './icons/thumbs_up_two.svg?raw'
import volumeHigh from './icons/volume_high.svg?raw'
import volumeOff from './icons/volume_off.svg?raw'
import subtitles from './icons/subtitles.svg?raw'
import arrowLeft from './icons/arrow_left.svg?raw'
import flag from './icons/flag.svg?raw'
import newEpisode from './icons/new_episode.svg?raw'
import refresh from './icons/refresh.svg?raw'
import audioDescription from './icons/audio_description.svg?raw'
import check from './icons/check.svg?raw'
import chevronDown from './icons/chevron-down.svg?raw'
import chevronLeft from './icons/chevron-left.svg?raw'
import chevronRight from './icons/chevron-right.svg?raw'
import info from './icons/info.svg?raw'
import maximize from './icons/maximize.svg?raw'
import pause from './icons/pause.svg?raw'

const RAW = {
  play, plus, search, bell, close, thumbsUp, thumbsDown, thumbsUpTwo, volumeHigh, volumeOff,
  subtitles, arrowLeft, flag, newEpisode, refresh, audioDescription, check, chevronDown,
  chevronLeft, chevronRight, info, maximize, pause,
}

// Inline the provided SVG icon set so `currentColor` and sizing follow CSS.
export function Icon({ name, size = 24, className = '', style }) {
  const raw = RAW[name] || ''
  const svg = raw
    .replace(/width="[^"]*"/, `width="${size}"`)
    .replace(/height="[^"]*"/, `height="${size}"`)
  return <span className={`icon ${className}`} style={{ width: size, height: size, ...style }}
    aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />
}

// Player glyphs the provided set does not include, drawn in the same 24px/stroke style.
export function SkipIcon({ dir = 'back', size = 40 }) {
  const flip = dir === 'back'
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <g transform={flip ? 'translate(24,0) scale(-1,1)' : undefined}>
        <path d="M12 3a9 9 0 1 0 9 9" stroke="currentColor" strokeWidth="1.8" fill="none" />
        <path d="M12 0.8v4.6l3.6-2.3z" fill="currentColor" />
        <path d="M17.2 2.6l2.9 1.6-2.9 1.7" stroke="currentColor" strokeWidth="1.4" fill="none" />
      </g>
      <text x="12" y="15.6" textAnchor="middle" fontSize="8.6" fontWeight="700" fill="currentColor"
        fontFamily="Inter, Arial, sans-serif">10</text>
    </svg>
  )
}

export function NextEpisodeIcon({ size = 40 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 3.5v17l13-8.5z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M20 3.5v17" stroke="currentColor" strokeWidth="2" />
    </svg>
  )
}

export function EpisodesIcon({ size = 40 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="2" y="10" width="15" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
      <path d="M5.5 7h13a1.5 1.5 0 0 1 1.5 1.5V16" stroke="currentColor" strokeWidth="1.8" />
      <path d="M9 4h11.5A1.5 1.5 0 0 1 22 5.5V12" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

export function ExitFullscreenIcon({ size = 40 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M8 3v5H3M16 3v5h5M8 21v-5H3M16 21v-5h5" stroke="currentColor" strokeWidth="2" />
    </svg>
  )
}

export function FullscreenIcon({ size = 40 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3 8V3h5M21 8V3h-5M3 16v5h5M21 16v5h-5" stroke="currentColor" strokeWidth="2" />
    </svg>
  )
}

export function PencilIcon({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 20h4L19 9l-4-4L4 16v4z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M13.5 6.5l4 4" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

export function UserIcon({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.8" />
      <path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

export function CaretDown({ size = 10 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 10 6" aria-hidden="true">
      <path d="M0 0h10L5 6z" fill="currentColor" />
    </svg>
  )
}
