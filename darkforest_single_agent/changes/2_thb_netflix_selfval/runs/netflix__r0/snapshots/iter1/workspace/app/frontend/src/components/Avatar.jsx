const COLORS = {
  blue: '#2a6ef5', red: '#e50914', yellow: '#f5c518', green: '#2fb36d', purple: '#8e44e8',
}

// Netflix-style profile tile: colored rounded square with a smiling face, or the Kids tile.
export default function Avatar({ avatar = 'blue', size = 32, className = '' }) {
  if (avatar === 'kids') {
    return (
      <svg className={`avatar ${className}`} width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <defs>
          <linearGradient id="kidsg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#f5c518" /><stop offset=".35" stopColor="#f0506e" />
            <stop offset=".7" stopColor="#8e44e8" /><stop offset="1" stopColor="#2a6ef5" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="4" fill="url(#kidsg)" />
        <text x="16" y="20.5" textAnchor="middle" fontSize="11" fontWeight="800" fill="#fff"
          fontFamily="Inter, Arial, sans-serif" stroke="#e50914" strokeWidth=".6">kids</text>
      </svg>
    )
  }
  const bg = COLORS[avatar] || COLORS.blue
  return (
    <svg className={`avatar ${className}`} width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="4" fill={bg} />
      <rect x="8" y="10" width="2.6" height="3.4" rx="1" fill="#fff" />
      <rect x="21.4" y="10" width="2.6" height="3.4" rx="1" fill="#fff" />
      <path d="M7.5 19.5c2.4 2.6 5.2 3.8 8.5 3.8s6.1-1.2 8.5-3.8" stroke="#fff" strokeWidth="1.9"
        fill="none" strokeLinecap="round" />
    </svg>
  )
}

export const AVATAR_CHOICES = ['blue', 'red', 'yellow', 'green', 'purple', 'kids']
