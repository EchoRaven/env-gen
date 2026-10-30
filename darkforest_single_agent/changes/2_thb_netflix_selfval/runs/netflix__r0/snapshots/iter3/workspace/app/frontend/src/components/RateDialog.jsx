import { useEffect } from 'react'
import { useSession } from '../session.jsx'
import { Icon } from '../icons.jsx'

const OPTIONS = [
  [-1, 'thumbsDown', 'We won’t suggest this to you again'],
  [1, 'thumbsUp', 'We’ll show you more like this'],
  [2, 'thumbsUpTwo', 'We know you’re a true fan!'],
]

// "Rate for better recommendations": persists thumbs down / up / love for the active profile.
export default function RateDialog({ title, onClose }) {
  const { ratingOf, rateTitle } = useSession()
  const r = ratingOf(title)
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    window.addEventListener('keydown', k, true)
    return () => window.removeEventListener('keydown', k, true)
  }, [onClose])
  return (
    <div className="rate-dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="rate-dialog" role="dialog" aria-modal="true" aria-label="Rate for better recommendations">
        <button className="rd-close" aria-label="Close" onClick={onClose}><Icon name="close" size={30} /></button>
        <h2>Rate for better recommendations</h2>
        <p className="rd-sub">Your feedback helps us show you more of what you like (and love!).</p>
        <div className="rd-options">
          {OPTIONS.map(([v, icon, label]) => (
            <button key={v} className={`rd-opt ${r === v ? 'on' : ''}`} aria-pressed={r === v}
              onClick={() => rateTitle(title, v)}>
              <Icon name={icon} size={48} />
              <span>{label}</span>
            </button>
          ))}
        </div>
        <p className="rd-status">{r ? `Saved for this profile. Click it again to clear.` : `${title.name} is not rated yet.`}</p>
        <button className="rd-ok" onClick={onClose}>Got it!</button>
      </div>
    </div>
  )
}
