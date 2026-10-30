export const LANGUAGES = {
  af: 'Afrikaans', ar: 'Arabic', da: 'Danish', de: 'German', en: 'English', es: 'Spanish', fr: 'French',
  hi: 'Hindi', it: 'Italian', ja: 'Japanese', ko: 'Korean', nl: 'Dutch', pt: 'Portuguese', ru: 'Russian',
  sv: 'Swedish', th: 'Thai', tr: 'Turkish', zh: 'Mandarin',
};

export function fmtDuration(min) {
  if (!min && min !== 0) return '';
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

export function fmtClock(sec) {
  if (!isFinite(sec) || sec < 0) sec = 0;
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = String(sec % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

// "2 Seasons" / "8 Episodes" / "1h 52m"
export function lengthLabel(t) {
  if (t.kind === 'series') {
    if (t.seasons > 1) return `${t.seasons} Seasons`;
    return `${t.episode_count} Episodes`;
  }
  return fmtDuration(t.duration);
}

export const CURRENT_YEAR = 2026;

export function badgeFor(t) {
  if (t.year >= CURRENT_YEAR) return t.kind === 'series' ? 'New Episodes' : 'Recently Added';
  return null;
}

export const kindLabel = (k) => (k === 'series' ? 'TV Shows' : 'Movies');

// Real clip lengths are learned by the player (loadedmetadata) and cached per video file.
export function clipLength(url) {
  const v = Number(localStorage.getItem(`nf_len_${url}`));
  return v > 0 ? v : null;
}
export function rememberClipLength(url, seconds) {
  if (url && seconds > 0 && isFinite(seconds)) localStorage.setItem(`nf_len_${url}`, String(seconds));
}
export function progressPct(item) {
  const len = clipLength(item.title?.video_url || item.video_url);
  if (!len) return item.progress_seconds > 0 ? 5 : 0;
  return Math.min(100, (item.progress_seconds / len) * 100);
}
