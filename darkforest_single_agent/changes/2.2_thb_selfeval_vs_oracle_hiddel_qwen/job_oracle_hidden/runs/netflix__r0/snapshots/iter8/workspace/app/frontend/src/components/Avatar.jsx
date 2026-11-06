import { avatarStyle } from '../lib/util'
import Icon from './Icon'

export default function Avatar({ profile, size = 34, showFace = false, className = '' }) {
  const style = avatarStyle(profile?.avatar)
  return (
    <span
      className={className}
      style={{
        width: size, height: size, borderRadius: 6,
        background: style.bg,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        fontSize: size * 0.45, flex: '0 0 auto',
      }}
      title={profile?.name}
    >
      {showFace ? (
        <span style={{ filter: 'grayscale(0.1)' }}>{style.face}</span>
      ) : (
        <span style={{ color: '#fff', fontWeight: 700, fontSize: size * 0.4, textShadow: '0 1px 2px rgba(0,0,0,0.5)' }}>
          {(profile?.name || '?').trim()[0]?.toUpperCase()}
        </span>
      )}
    </span>
  )
}
