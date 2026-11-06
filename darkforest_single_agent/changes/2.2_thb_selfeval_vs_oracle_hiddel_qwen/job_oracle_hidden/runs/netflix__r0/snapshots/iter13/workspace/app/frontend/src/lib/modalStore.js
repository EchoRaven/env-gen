// Lightweight global "open title detail modal" channel (window CustomEvent).
export function openTitleModal(titleId) {
  window.dispatchEvent(new CustomEvent('nf-open-title', { detail: { id: titleId } }))
}
export function onOpenTitle(cb) {
  const handler = (e) => cb(e.detail?.id)
  window.addEventListener('nf-open-title', handler)
  return () => window.removeEventListener('nf-open-title', handler)
}
