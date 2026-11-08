import React from 'react'
import { useNavigate } from 'react-router-dom'
import { assetUrl } from '../api'
import Icon from './Icon'
import { useOpenTitle } from '../hooks'

export default function Hero({ title, eyebrow = 'Featured' }) {
  const navigate = useNavigate()
  const openTitle = useOpenTitle()
  if (!title) {
    return <section className="hero hero-skeleton"><div className="hero-shimmer" /></section>
  }
  return (
    <section className="hero">
      <div className="hero-backdrop">
        <img src={assetUrl(title.backdrop || title.poster)} alt="" />
      </div>
      <div className="hero-vignette" />
      <div className="hero-fade" />
      <div className="hero-copy">
        <div className="hero-eyebrow"><span className="n-mark">N</span> {eyebrow}</div>
        <h1>{title.name}</h1>
        <div className="hero-meta">
          <span className="match">{Math.max(72, Math.round((title.rating || 6) * 10))}% Match</span>
          <span>{title.year}</span>
          <span className="maturity-badge">{title.maturity_rating}</span>
          <span>{title.kind === 'series' ? `${title.seasons || 1} Season${title.seasons === 1 ? '' : 's'}` : title.duration_label}</span>
          <span className="hd">HD</span>
        </div>
        <p className="hero-synopsis">{title.synopsis || 'Synopsis unavailable.'}</p>
        <div className="hero-actions">
          <button className="btn btn-play" onClick={() => navigate(`/watch/${title.id}`)}>
            <Icon name="play" size={22} /> Play
          </button>
          <button className="btn btn-secondary" onClick={() => openTitle(title.id)}>
            <Icon name="info" size={22} /> More Info
          </button>
        </div>
      </div>
    </section>
  )
}
