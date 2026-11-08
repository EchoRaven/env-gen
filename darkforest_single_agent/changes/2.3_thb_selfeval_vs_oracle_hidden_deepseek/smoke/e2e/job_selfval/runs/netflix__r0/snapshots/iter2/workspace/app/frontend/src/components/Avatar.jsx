const AVATARS = {
  crimson: { a: '#e50914', b: '#4b0b10' },
  blue: { a: '#3f82ff', b: '#102e5c' },
  gold: { a: '#f3b63f', b: '#5b3b06' },
  green: { a: '#36b37e', b: '#0c3c2b' },
  violet: { a: '#9a6bff', b: '#30165d' },
  slate: { a: '#8b9bb4', b: '#2c3442' },
}

export default function Avatar({ profile, size = 42, className = '', showFace = true }) {
  const palette = AVATARS[profile?.avatar] || AVATARS.crimson
  const initial = (profile?.name || '?').trim().charAt(0).toUpperCase() || '?'
  return (
    <span
      className={`avatar ${className}`}
      style={{
        width: size,
        height: size,
        borderRadius: Math.max(6, Math.round(size * 0.16)),
        background: `radial-gradient(circle at 68% 18%, ${palette.a}, ${palette.b} 72%)`,
        fontSize: Math.max(12, Math.round(size * 0.4)),
      }}
      aria-label={profile?.name || 'Profile'}
    >
      {showFace ? (
        <>
          <span className="avatar-face" aria-hidden="true" />
          <span className="avatar-initial" aria-hidden="true">{initial}</span>
        </>
      ) : null}
    </span>
  )
}

export const avatarChoices = Object.keys(AVATARS)
