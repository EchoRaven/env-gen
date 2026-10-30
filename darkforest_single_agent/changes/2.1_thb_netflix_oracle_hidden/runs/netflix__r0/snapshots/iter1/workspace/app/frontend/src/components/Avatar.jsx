const COLORS = {
  blue: '#2f6fe4', red: '#e50914', yellow: '#f5b81c', green: '#2fa04a', purple: '#7b3fe4',
};

export default function Avatar({ avatar = 'blue', size = 36, radius = 4 }) {
  if (avatar === 'kids') {
    return (
      <svg width={size} height={size} viewBox="0 0 36 36" style={{ borderRadius: radius, display: 'block' }} aria-hidden="true">
        <defs>
          <linearGradient id="kidsg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#f5c518" />
            <stop offset=".35" stopColor="#ef5a8f" />
            <stop offset=".7" stopColor="#7b5cf0" />
            <stop offset="1" stopColor="#2fb4e9" />
          </linearGradient>
        </defs>
        <rect width="36" height="36" fill="url(#kidsg)" />
        <text x="18" y="22.5" textAnchor="middle" fontFamily="Inter, Arial" fontWeight="800" fontSize="11" fill="#fff" stroke="#c0186b" strokeWidth=".6">kids</text>
      </svg>
    );
  }
  const c = COLORS[avatar] || COLORS.blue;
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" style={{ borderRadius: radius, display: 'block' }} aria-hidden="true">
      <rect width="36" height="36" fill={c} />
      <rect x="9" y="11" width="3" height="4" rx="1" fill="#fff" />
      <rect x="24" y="11" width="3" height="4" rx="1" fill="#fff" />
      <path d="M8 21c5 5 15 5 20 0" stroke="#fff" strokeWidth="2.4" fill="none" strokeLinecap="round" />
    </svg>
  );
}
