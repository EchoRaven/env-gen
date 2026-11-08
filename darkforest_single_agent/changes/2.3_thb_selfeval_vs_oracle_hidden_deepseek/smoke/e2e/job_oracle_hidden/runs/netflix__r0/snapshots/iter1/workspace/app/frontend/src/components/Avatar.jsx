import React from 'react'

const palettes = {
  red: ['#e50914', '#7a050b'],
  blue: ['#2d6cdf', '#112f68'],
  green: ['#2d9c65', '#0c4328'],
  yellow: ['#e6a516', '#755108'],
  purple: ['#8d55d9', '#3b1f67'],
  pink: ['#dc5591', '#681936'],
}

export default function Avatar({ profile, size = 40, className = '' }) {
  const key = profile?.avatar || 'red'
  const colors = palettes[key] || palettes.red
  return (
    <span
      className={`avatar ${className} ${profile?.is_kids ? 'kids-avatar' : ''}`}
      style={{
        width: size, height: size,
        background: `linear-gradient(145deg, ${colors[0]}, ${colors[1]})`,
      }}
      aria-label={profile?.name || 'Profile'}
    >
      <span className="avatar-head" />
      <span className="avatar-body" />
      <span className="avatar-initial">{profile?.name?.slice(0, 1).toUpperCase() || ''}</span>
    </span>
  )
}
