// Resolve stored media paths ("assets/posters/x.jpg", "/media/...") to app-absolute URLs.
export function mediaUrl(path) {
  if (!path) return '';
  if (path.startsWith('assets/')) return '/media/' + path.slice('assets/'.length);
  if (path.startsWith('http')) return path;
  return path;
}

export function fmtDuration(seconds) {
  if (!seconds || seconds <= 0) return '';
  const m = Math.round(seconds / 60);
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (h > 0) return `${h}h ${mm > 0 ? mm + 'm' : ''}`.trim();
  return `${m}m`;
}

export function fmtClock(seconds) {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  const s = Math.floor(seconds % 60);
  const m = Math.floor((seconds / 60) % 60);
  const h = Math.floor(seconds / 3600);
  const mm = h > 0 ? String(m).padStart(2, '0') : String(m);
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

export function matchPct(rating) {
  if (rating == null) return null;
  return Math.min(99, Math.round((rating / 10) * 100));
}

export function clamp(v, min, max) { return Math.min(max, Math.max(min, v)); }

const AVATAR_STYLES = [
  { bg: 'linear-gradient(135deg, #1f4037, #99f2c8)', face: '🙂' },
  { bg: 'linear-gradient(135deg, #3a2a64, #a78bfa)', face: '😎' },
  { bg: 'linear-gradient(135deg, #7b2d2d, #f59e0b)', face: '🧒' },
  { bg: 'linear-gradient(135deg, #14532d, #4ade80)', face: '🤓' },
  { bg: 'linear-gradient(135deg, #1e3a8a, #38bdf8)', face: '🥸' },
  { bg: 'linear-gradient(135deg, #701a75, #f472b6)', face: '😺' },
];

export function avatarStyle(avatarKey) {
  if (!avatarKey) return AVATAR_STYLES[0];
  const m = String(avatarKey).match(/(\d+)$/);
  const idx = m ? (parseInt(m[1], 10) % AVATAR_STYLES.length) : 0;
  return AVATAR_STYLES[idx];
}

export function initials(name) {
  return (name || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0].toUpperCase()).join('');
}
