import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useAsync, useSession } from '../session.jsx'

// The seeded catalog (dataset/titles.json) contains movies and series only — no games.
// This page reports that honestly instead of inventing game titles.
export default function Games() {
  const { profileId } = useSession()
  const { data } = useAsync(() => api.titles({ kind: 'game', limit: 1 }), [profileId])
  const count = data?.total ?? null
  return (
    <div className="games-page">
      <div className="games-hero">
        <h1>Games</h1>
        <p className="games-meta"><span>Game</span><i className="dot" /><span>Play on any device</span></p>
      </div>
      <section className="row">
        <div className="row-head"><h2 className="row-title">Party Games <span className="beta">BETA</span></h2></div>
        {count === null
          ? <p className="row-empty">Loading…</p>
          : count === 0
            ? (
              <div className="empty-state">
                <h3>No games in the catalog yet</h3>
                <p>This library currently has movies and TV shows only. Games will appear here when they are added.</p>
                <div className="empty-actions">
                  <Link className="btn-white" to="/shows">Browse TV Shows</Link>
                  <Link className="btn-grey" to="/movies">Browse Movies</Link>
                </div>
              </div>
            )
            : <p className="row-empty">{count} games available.</p>}
      </section>
    </div>
  )
}
