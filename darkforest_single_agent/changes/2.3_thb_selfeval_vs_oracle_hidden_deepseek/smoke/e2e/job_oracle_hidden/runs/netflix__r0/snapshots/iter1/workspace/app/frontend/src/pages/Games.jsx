import React from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from '../components/Icon'

export default function Games() {
  const navigate = useNavigate()
  return (
    <div className="browse-page games-page">
      <section className="games-hero">
        <div className="games-hero-bg" />
        <div className="games-hero-copy">
          <span className="hero-eyebrow"><span className="n-mark">N</span> GAMES</span>
          <h1>Games</h1>
          <p>Games are included with your Netflix membership. This local catalog does not contain game assets.</p>
          <div className="hero-actions">
            <button className="btn btn-secondary" onClick={() => navigate('/browse')}>Browse Titles</button>
          </div>
        </div>
      </section>
      <div className="rows-container raised games-rows">
        <section className="rail empty-rail">
          <div className="rail-heading"><h2>Party Games</h2></div>
          <div className="games-empty">
            <span className="empty-icon"><Icon name="info" size={48} /></span>
            <h3>No games in this catalog</h3>
            <p>The supplied catalog contains movies and series only. Nothing has been fabricated to fill this row.</p>
            <button className="btn btn-secondary" onClick={() => navigate('/movies')}>Explore Movies</button>
          </div>
        </section>
      </div>
    </div>
  )
}
