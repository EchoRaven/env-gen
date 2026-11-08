import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import HeroBillboard from '../components/HeroBillboard.jsx'
import PosterRail from '../components/PosterRail.jsx'
import { useTitleOverlay } from '../components/useTitleOverlay.js'
import GenreMenu from '../components/GenreMenu.jsx'

export default function GamesPage() {
  const { api } = useAuth()
  const { openTitle } = useTitleOverlay()
  const [titles, setTitles] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    api.get('/api/titles?genre=Reality&limit=24').then((result) => {
      if (!cancelled) setTitles(result.items || [])
    }).catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [api])

  return (
    <PageShell className="browse-app">
      <div className="browse-main">
        {error && <div className="page-error">{error}</div>}
        <HeroBillboard title={titles[0]} eyebrow="NETFLIX" pageLabel="Games" onMoreInfo={openTitle} />
        <div className="browse-rows with-genre-bar">
          <GenreMenu />
          <h1 className="page-heading">Games</h1>
          <PosterRail title="Game Shows" items={titles} onOpen={openTitle} />
          <PosterRail title="Party Games" items={[]} onOpen={openTitle} showEmpty />
          <div className="games-honest-note">
            <h2>About games on this catalog</h2>
            <p>The provided catalog contains films and series only. Interactive Netflix Games are not part of this dataset, so this page shows real game-show titles and an honest empty state for Party Games.</p>
          </div>
        </div>
      </div>
    </PageShell>
  )
}
