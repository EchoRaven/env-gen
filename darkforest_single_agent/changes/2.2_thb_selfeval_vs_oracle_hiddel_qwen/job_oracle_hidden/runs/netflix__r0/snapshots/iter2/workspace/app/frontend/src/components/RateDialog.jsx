import Icon from './Icon'
import { useApp } from '../state/AppContext'

const OPTS = [
  { value: 1, icon: 'thumbs_down', label: 'Not for me' },
  { value: 2, icon: 'thumbs_up', label: 'I like it' },
  { value: 3, icon: 'thumbs_up_two', label: 'I love it' },
]

export default function RateDialog({ titleId, titleName, initial, onClose }) {
  const { ratings, setRatingValue } = useApp()
  const current = ratings[titleId]

  const pick = (value) => {
    setRatingValue(titleId, value).catch(() => {})
    onClose()
  }

  return (
    <div className="rate-dialog" onClick={onClose}>
      <div className="rate-dialog-card" onClick={(e) => e.stopPropagation()}>
        <button className="icon-btn rate-close" aria-label="Close" onClick={onClose}><Icon name="close" size={18} /></button>
        <h3>Rate for better recommendations</h3>
        <p>How did you like “{titleName}”?</p>
        <div className="rate-options">
          {OPTS.map((o) => (
            <div key={o.value} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <button
                className={`rate-opt ${current === o.value ? 'selected' : ''}`}
                onClick={() => pick(o.value)}
                aria-label={o.label}
              >
                <Icon name={o.icon} size={30} />
              </button>
              <span className="rate-opt-label">{o.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
