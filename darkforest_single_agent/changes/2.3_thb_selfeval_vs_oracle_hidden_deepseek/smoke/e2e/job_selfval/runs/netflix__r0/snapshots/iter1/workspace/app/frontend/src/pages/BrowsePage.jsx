import { useEffect, useMemo, useState } from 'react'
import api from '../api'
import Hero from '../components/Hero'
import Spinner from '../components/Spinner'
import TitleModal from '../components/TitleModal'
import TitleRail from '../components/TitleRail'
import { useAuth } from '../context/AuthContext'

export default function BrowsePage() {
  const [trending, setTrending] = useState([])
  const [continueItems, setContinueItems] = useState([])
  const [top10, setTop10] = useState([])
  const [allTitles, setAllTitles] = useState([])
  const [genreTitles, setGenreTitles] = useState([])
  const [actionGenre, setActionGenre] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedTitle, setSelectedTitle] = useState(null)
  const { profile } = useAuth()

  const load = async () => {
    setLoading(true)
    try {
      const [trendingData, continueData, topData, allData, genreData] = await Promise.all([
        api.get('/api/titles/trending'),
        api.get('/api/continue-watching'),
        api.get('/api/titles/top10'),
        api.get('/api/titles?sort=newest'),
        api.get('/api/genres'),
      ])
      setTrending(trendingData.items || [])
      setContinueItems(continueData.items || [])
      setTop10(topData.items || [])
      setAllTitles(allData.items || [])
      const action = (genreData.items || []).find((genre) => genre.name === 'Action & Adventure')
      setActionGenre(action || (genreData.items || [])[0] || null)
      if (action) {
        const data = await api.get(`/api/genres/${action.id}/titles`)
        setGenreTitles((data.items || []).filter((title) => title.kind === 'series'))
      } else {
        setGenreTitles([])
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [profile?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const heroTitle = useMemo(() => {
    return trending.find((title) => title.id === 36) || trending[0] || allTitles[0] || null
  }, [trending, allTitles])

  const newTitles = useMemo(() => [...allTitles].sort((a, b) => b.year - a.year || b.id - a.id), [allTitles])
  const topSearches = useMemo(() => [...allTitles].sort((a, b) => b.rating - a.rating).slice(0, 18), [allTitles])
  const onlyOnNetflix = useMemo(() => allTitles.filter((title) => title.year >= 2024).slice(0, 18), [allTitles])

  if (loading && !trending.length) {
    return <div className="page-loading"><Spinner label="Loading your Netflix home…" /></div>
  }

  return (
    <div className="browse-page">
      <Hero title={heroTitle} onMoreInfo={setSelectedTitle} loading={loading && !heroTitle} className="home-hero" />
      <div className="page-content home-content">
        <TitleRail title="Trending Now" items={trending} onOpen={setSelectedTitle} onChanged={load} />
        <TitleRail
          title="Continue Watching"
          items={continueItems}
          continueRail
          onOpen={setSelectedTitle}
          onChanged={load}
          emptyMessage={profile ? `Start watching something, ${profile.name}. Your progress will appear here.` : 'Titles you start will appear here.'}
        />
        <TitleRail
          title={actionGenre ? `TV ${actionGenre.name}` : 'TV Action & Adventure'}
          items={genreTitles}
          onOpen={setSelectedTitle}
          onChanged={load}
          emptyMessage="No series currently match this genre."
        />
        <TitleRail
          title="Top 10 in Your Country Today"
          items={top10}
          top10
          onOpen={setSelectedTitle}
          onChanged={load}
        />
        <TitleRail
          title="Only on Netflix"
          items={onlyOnNetflix}
          onOpen={setSelectedTitle}
          onChanged={load}
          emptyMessage="No catalog titles currently match this collection."
        />
        <TitleRail
          title="Games"
          items={[]}
          onOpen={setSelectedTitle}
          onChanged={load}
          emptyMessage="Game titles are not included in this catalog. Explore the available films and series instead."
        />
        <TitleRail title="Top Searches" items={topSearches} onOpen={setSelectedTitle} onChanged={load} />
        <TitleRail title="New on Netflix" items={newTitles} onOpen={setSelectedTitle} onChanged={load} />
        <div className="catalog-footer">
          <p>60 titles · 112 episodes · Real artwork and trailers</p>
          <span>Profiles keep My List, ratings, and viewing progress private.</span>
        </div>
      </div>
      {selectedTitle ? (
        <TitleModal titleId={selectedTitle.id} initialTitle={selectedTitle} onClose={() => setSelectedTitle(null)} onChanged={load} />
      ) : null}
    </div>
  )
}
