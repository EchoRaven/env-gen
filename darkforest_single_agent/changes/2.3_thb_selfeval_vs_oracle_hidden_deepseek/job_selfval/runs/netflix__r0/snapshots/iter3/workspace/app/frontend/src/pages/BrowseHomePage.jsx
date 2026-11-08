import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import PageShell from '../components/PageShell.jsx'
import HeroBillboard from '../components/HeroBillboard.jsx'
import PosterRail from '../components/PosterRail.jsx'
import { useTitleOverlay } from '../components/useTitleOverlay.js'

export default function BrowseHomePage() {
  const { api, activeProfile } = useAuth()
  const { openTitle } = useTitleOverlay()
  const [data, setData] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      api.get('/api/titles/trending?limit=24'),
      api.get('/api/continue-watching'),
      api.get('/api/titles/top10'),
      api.get('/api/titles?sort=new&limit=24'),
      api.get('/api/titles?genre=Action%20%26%20Adventure&limit=24'),
      api.get('/api/titles?genre=Sci-Fi%20%26%20Fantasy&kind=series&limit=24'),
      api.get('/api/my-list'),
    ]).then(([trending, continueWatching, top10, newest, action, sciFi, myList]) => {
      if (cancelled) return
      setData({
        trending: trending.items || [],
        continueWatching: continueWatching.items || [],
        top10: top10.items || [],
        newest: newest.items || [],
        action: action.items || [],
        sciFi: sciFi.items || [],
        myList: myList.items || [],
      })
    }).catch((err) => {
      if (!cancelled) setError(err.message)
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [api])

  const hero = data.trending?.[0] || data.newest?.[0]

  return (
    <PageShell className="browse-app">
      <div className="browse-main">
        {loading && <div className="page-loading">Loading your Netflix…</div>}
        {error && <div className="page-error">{error}</div>}
        {!loading && (
          <>
            <HeroBillboard title={hero} eyebrow={hero?.kind === 'series' ? 'SERIES' : 'FILM'} onMoreInfo={openTitle}>
              {activeProfile?.is_kids && <p className="kids-note">Kids profile · family-friendly picks are marked with a kids badge.</p>}
            </HeroBillboard>
            <div className="browse-rows">
              <PosterRail title="Trending Now" items={data.trending} onOpen={openTitle} />
              {(data.continueWatching?.length || 0) > 0 && (
                <PosterRail title={`Continue Watching for ${activeProfile?.name || 'You'}`} items={data.continueWatching} onOpen={openTitle} progress />
              )}
              <PosterRail title="TV Action & Adventure" items={data.action} onOpen={openTitle} />
              <PosterRail title="Games" items={[]} onOpen={openTitle} showEmpty />
              <PosterRail title="Only on Netflix" items={data.top10} onOpen={openTitle} />
              <PosterRail title="Top Searches" items={data.top10} onOpen={openTitle} variant="top10" />
              <PosterRail title="New on Netflix" items={data.newest} onOpen={openTitle} />
              <PosterRail title="Sci-Fi & Fantasy" items={data.sciFi} onOpen={openTitle} />
              {(data.myList?.length || 0) > 0 && <PosterRail title="My List" items={data.myList} onOpen={openTitle} />}
            </div>
          </>
        )}
      </div>
    </PageShell>
  )
}
