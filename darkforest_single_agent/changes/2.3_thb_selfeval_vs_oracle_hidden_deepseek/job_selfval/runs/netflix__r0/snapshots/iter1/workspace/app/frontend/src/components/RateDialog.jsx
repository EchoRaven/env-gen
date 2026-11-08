import { useState } from 'react'
import { createPortal } from 'react-dom'
import Icon from './Icon.jsx'
import { useAuth } from '../context/AuthContext.jsx'

const OPTIONS = [
  { value: -1, icon: 'thumbs-down', label: 'Not for me', help: "We won't suggest this to you again", className: 'down' },
  { value: 1, icon: 'thumbs-up', label: 'I like this', help: "We'll show you more like this", className: 'up' },
  { value: 2, icon: 'thumbs-up', label: 'Love this!', help: "We know you're a true fan!", className: 'love' },
]

export default function RateDialog({ title, currentValue, onClose, onRated }) {
  const { api } = useAuth()
  const [selected, setSelected] = useState(currentValue ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function choose(value) {
    setBusy(true)
    setError('')
    try {
      const result = await api.post(`/api/titles/${title.id}/rating`, { value })
      setSelected(result.item?.user_rating ?? value)
      onRated?.(result.item?.user_rating ?? value)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div className="rate-overlay" role="dialog" aria-modal="true" aria-label="Rate this title" onClick={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div className="rate-dialog">
        <button type="button" className="modal-close small" onClick={onClose} aria-label="Close rating dialog"><Icon name="x" size={18} /></button>
        <div className="rate-title-visual" style={{ backgroundImage: `url(${title.backdrop || title.poster})` }} />
        <h2>Rate for better recommendations</h2>
        <p className="rate-subtitle">Your feedback helps us show you more of what you like (and love!). Your rating is private to <strong>{title.name}</strong>'s profile.</p>
        <div className="rate-options">
          {OPTIONS.map((option) => (
            <button
              type="button"
              key={option.value}
              className={`rate-option ${option.className} ${selected === option.value ? 'selected' : ''}`}
              onClick={() => choose(option.value)}
              disabled={busy}
              aria-label={option.label}
            >
              <span className={`rate-icon ${option.value === 2 ? 'double' : ''}`}>
                <Icon name={option.icon} size={30} />
                {option.value === 2 && <Icon name={option.icon} size={30} />}
              </span>
              <span>{option.label}</span>
              <span className="rate-help">{option.help}</span>
            </button>
          ))}
        </div>
        <div className="rate-footer">
          {selected != null ? <div className="rate-confirmation">Saved for this profile</div> : <span />}
          <button type="button" className="btn btn-play btn-small" onClick={onClose}>Got it!</button>
        </div>
        {error && <div className="form-error">{error}</div>}
      </div>
    </div>,
    document.body,
  )
}
