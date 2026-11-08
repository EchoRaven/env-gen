import { PROFILE_COLORS } from '../utils'

export function ProfileAvatar({ profile, size = 32, className = '' }) {
  if (!profile) return null
  const colors = PROFILE_COLORS[profile.avatar] || PROFILE_COLORS.red
  const initials = profile.name
    .split(/\s+/)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
  return (
    <span
      className={`profile-avatar ${className}`}
      style={{
        width: size,
        height: size,
        background: `linear-gradient(145deg, ${colors[0]}, ${colors[1]})`,
        fontSize: Math.max(10, size * 0.32),
        borderRadius: Math.max(4, size * 0.12),
      }}
      aria-hidden="true"
    >
      {initials}
    </span>
  )
}
