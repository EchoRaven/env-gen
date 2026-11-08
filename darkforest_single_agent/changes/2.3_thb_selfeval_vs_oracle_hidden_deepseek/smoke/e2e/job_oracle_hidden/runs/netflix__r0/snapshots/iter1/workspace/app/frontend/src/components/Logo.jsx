import React from 'react'
import { Link } from 'react-router-dom'

export default function Logo({ to = '/browse', className = '' }) {
  return (
    <Link to={to} className={`logo ${className}`} aria-label="Netflix home">
      <img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" />
    </Link>
  )
}
