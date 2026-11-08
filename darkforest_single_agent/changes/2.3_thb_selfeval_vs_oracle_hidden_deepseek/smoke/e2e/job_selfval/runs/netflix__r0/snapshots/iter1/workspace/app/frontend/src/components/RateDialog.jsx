import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import api from '../api'
import Icon from './Icon'
import { useToast } from '../context/ToastContext'

const OPTIONS = [
  { value: -1, icon: 'thumbDown', label: 'Not for me' },
  { value: 1, icon: 'thumbUp', label: 'I like this' },
  { value: 2, icon: 'love', label: 'Love this!' },
]

export default function RateDialog({ title, initialValue, onClose, onRated }) {
  const [value, setValue] = useState(initialValue || null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const { notify } = useToast()

  useEffect(() => {
    setValue(initialValue || null)
  }, [initialValue, title?.id])

  if (!title) return null

  const save = async () => {
    if (!value) return
    const next = value
    setSaving(true)
    setError('')
    try {
      await api.post(`/api/titles/${title.id}/rating`, { value: next })
      setValue(next)
      notify('Your rating was saved.', 'success')
      onRated?.(next)
      onClose?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return createPortal(
    <div className="dialog-backdrop rate-backdrop" onClick={(e) => e.stopPropagation()} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <section className="rate-dialog" role="dialog" aria-modal="true" aria-labelledby="rate-title">
        <button className="icon-btn dialog-close" onClick={onClose} aria-label="Close rating dialog">
          <Icon name="close" size={22} />
        </button>
        <h2 id="rate-title">Rate for better recommendations</h2>
        <p className="rate-subtitle">Your ratings help us find more titles you’ll love on {title.name} and beyond.</p>
        <div className="rate-options">
          {OPTIONS.map((option) => (
            <button
              key={option.value}
              className={`rate-option ${value === option.value ? 'selected' : ''}`}
              onClick={() => setValue(option.value)}
              disabled={saving}
            >
              <span className="rate-icon"><Icon name={option.icon} size={30} /></span>
              <span>{option.label}</span>
            </button>
          ))}
        </div>
        <button className="btn btn-light rate-confirm" onClick={save} disabled={!value || saving}>
          {saving ? 'Saving…' : 'Got it!'}
        </button>
        <div className="rate-current">
          {value ? 'Select Got it! to save your rating.' : 'Choose one rating'}
        </div>
        {error ? <p className="form-error">{error}</p> : null}
      </section>
    </div>,
    document.body,
  )
}
