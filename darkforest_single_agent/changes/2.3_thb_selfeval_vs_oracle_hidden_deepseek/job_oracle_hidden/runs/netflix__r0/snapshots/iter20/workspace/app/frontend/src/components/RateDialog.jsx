import { useState } from 'react'
import { useAuth } from '../AuthContext'
import { AssetIcon } from '../icons'

const OPTIONS = [
  { value: -1, label: 'Not for me', icon: 'thumbs_down' },
  { value: 1, label: 'I like this', icon: 'thumbs_up' },
  { value: 2, label: 'Love this!', icon: 'thumbs_up_two' },
]

export function RateDialog({ title, currentValue, onClose, onRated }) {
  const { authFetch } = useAuth()
  const [selected, setSelected] = useState(currentValue ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const choose = async (value) => {
    setBusy(true)
    setError('')
    try {
      await authFetch(`/api/titles/${title.id}/rating`, { method: 'POST', body: { value } })
      setSelected(value)
      onRated?.(value)
    } catch (requestError) {
      setError(requestError.message || 'Could not save your rating.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop rate-modal-backdrop" onClick={onClose}>
      <div className="rate-dialog" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="rate-heading">
        <button className="modal-close" onClick={onClose} aria-label="Close rating dialog">
          <AssetIcon name="close" size={22} />
        </button>
        <p className="rate-eyebrow">Rate this title</p>
        <h2 id="rate-heading">Rate for better recommendations</h2>
        <p className="rate-subtitle">Your feedback helps us show you more of what you like (and love!).</p>
        <p className="rate-title-name">{title.name}</p>
        <div className="rate-options">
          {OPTIONS.map((option) => (
            <button
              key={option.value}
              className={`rate-option ${selected === option.value ? 'selected' : ''}`}
              onClick={() => choose(option.value)}
              disabled={busy}
              aria-pressed={selected === option.value}
            >
              <span className="rate-icon">
                <AssetIcon name={option.icon} size={34} />
              </span>
              <span>{option.label}</span>
            </button>
          ))}
        </div>
        {error ? <p className="form-error">{error}</p> : null}
        {selected !== null && !error ? <p className="rate-saved">Your rating is saved to this profile.</p> : null}
        <button className="rate-got-it" onClick={onClose}>Got it</button>
      </div>
    </div>
  )
}
