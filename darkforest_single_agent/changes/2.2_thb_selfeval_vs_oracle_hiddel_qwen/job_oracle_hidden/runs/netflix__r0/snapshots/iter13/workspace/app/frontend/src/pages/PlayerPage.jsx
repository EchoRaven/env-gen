import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useApp } from '../state/AppContext'
import Player from '../components/Player'

export default function PlayerPage() {
  const { titleId } = useParams()
  const [params] = useSearchParams()
  const episodeId = params.get('episode') ? parseInt(params.get('episode'), 10) : null
  const { saveProgress, profile } = useApp()
  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [resumeFrom, setResumeFrom] = useState(0)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setTitle(null); setEpisodes([]); setResumeFrom(0); setError(null)
    api(`/api/titles/${titleId}`)
      .then(async (t) => {
        if (!alive) return
        setTitle(t)
        let eps = []
        if (t.kind === 'series') {
          try {
            const ep = await api(`/api/titles/${titleId}/episodes`)
            eps = Array.isArray(ep) ? ep : (ep?.episodes || [])
          } catch { eps = [] }
        }
        if (!alive) return
        setEpisodes(eps)
        try {
          const cw = await api('/api/continue-watching')
          const row = (cw || []).find((x) => x.id === t.id)
          if (row && row.progress_seconds > 5) setResumeFrom(row.progress_seconds)
        } catch { /* ignore */ }
      })
      .catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [titleId])

  if (error) {
    return (
      <div className="player-root" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16 }}>
        <div style={{ fontSize: 1.2 }}>This title is not available.</div>
        <button className="btn btn-red" style={{ padding: '10px 22px', fontSize: '0.95rem' }} onClick={() => window.history.back()}>Go back</button>
      </div>
    )
  }
  if (!title) return <div className="player-root" />

  return (
    <Player
      title={title}
      episodes={title.kind === 'series' ? episodes : []}
      startEpisodeId={episodeId}
      resumeFrom={resumeFrom}
      onBack={() => window.history.back()}
      saveProgress={saveProgress}
    />
  )
}
