import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import Hero from '../components/Hero'
import Rail from '../components/Rail'
import Icon from '../components/Icon'
import { api } from '../lib/api'
import { useFetch, topN, newest, pickHero } from '../lib/hooks'
import { openTitleModal } from '../lib/modalStore'
import { useApp } from '../state/AppContext'

export default function Browse() {
  const nav = useNavigate()
  const { myListIds } = useApp()
  const { data: titles, loading } = useFetch('/api/titles')
  const { data: trending } = useFetch('/api/titles/trending')
  const { data: myList } = useFetch('/api/my-list')
  const { data: continueWatching } = useFetch('/api/continue-watching')

  const pool = useMemo(() => titles || [], [titles])
  const hero = useMemo(() => pickHero([...(pool.filter((t) => t.kind === 'series')), ...pool.slice(0, 10)]), [pool])
  const onlyNetflix = useMemo(() => topN(pool, 10), [pool])
  const newOnNetflix = useMemo(() => newest(pool, 12), [pool])
  const actionAdventure = useMemo(() => pool.filter((t) => t.kind === 'series' && t.genre === 'Action & Adventure'), [pool])
  const topSearches = useMemo(() => topN(pool, 10).map((t) => t.name), [pool])

  if (loading) return <div className="page-pad" style={{ minHeight: '100vh' }} />

  return (
    <div style={{ minHeight: '100vh' }}>
      <Header />
      {hero && <Hero title={hero} />}
      <div style={{ marginTop: -40, position: 'relative', zIndex: 5, paddingBottom: 40 }}>
        <Rail title="Trending Now" items={trending || []} emptyText="Nothing trending yet." />
        <Rail title="Continue Watching" items={continueWatching || []} emptyText="You haven’t watched anything yet. Pick a title to start." />
        <Rail title="TV Action & Adventure" items={actionAdventure} emptyText="No action & adventure series right now." />
        <section className="rail">
          <h2 className="rail-title">Games</h2>
          <div className="rail-empty">
            No games available in this catalog yet.{' '}
            <a href="#/games" onClick={(e) => { e.preventDefault(); nav('/games') }} style={{ color: '#e5e5e5', textDecoration: 'underline' }}>See the Games page</a>
          </div>
        </section>
        <Rail title="Only on Netflix" items={onlyNetflix} emptyText="Nothing here yet." />
        <section className="rail">
          <h2 className="rail-title">Top Searches</h2>
          <div className="rail-scroll">
            {topSearches.map((name) => (
              <span key={name} className="text-search-card" onClick={() => nav(`/search?q=${encodeURIComponent(name)}`)} role="button" tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && nav(`/search?q=${encodeURIComponent(name)}`)}>
                {name}
              </span>
            ))}
          </div>
        </section>
        <Rail title="New on Netflix" items={newOnNetflix} emptyText="No new titles yet." />
      </div>
    </div>
  )
}
