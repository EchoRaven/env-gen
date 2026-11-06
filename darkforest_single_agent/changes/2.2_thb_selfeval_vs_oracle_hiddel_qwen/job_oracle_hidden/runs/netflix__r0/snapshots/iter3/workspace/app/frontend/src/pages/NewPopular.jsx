import { useMemo } from 'react'
import Header from '../components/Header'
import Rail from '../components/Rail'
import { Top10Rail } from '../components/Rail'
import { useFetch, newest } from '../lib/hooks'
import { mediaUrl } from '../lib/util'
import { openTitleModal } from '../lib/modalStore'

function ComingThisWeek({ items }) {
  if (!items.length) return null
  return (
    <section className="rail">
      <h2 className="rail-title">Coming This Week</h2>
      <div className="rail-scroll">
        {items.map((t) => (
          <div key={t.id} className="new-card" onClick={() => openTitleModal(t.id)} role="button" tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && openTitleModal(t.id)}>
            <img src={mediaUrl(t.backdrop || t.poster)} alt="" loading="lazy" />
            <span className="nc-label">{t.year}</span>
            <div className="nc-name">{t.name}</div>
            <div className="nc-sub">{t.genre || (t.genres || [])[0] || '—'}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function NewPopular() {
  const { data: top10, loading } = useFetch('/api/titles/top10')
  const { data: all } = useFetch('/api/titles')
  const top10Series = useMemo(() => (top10 || []).filter((t) => t.kind === 'series'), [top10])
  const top10Movies = useMemo(() => (top10 || []).filter((t) => t.kind === 'movie'), [top10])
  // 'Coming This Week' = titles dated in the latest year of the catalog (genuinely unreleased)
  const coming = useMemo(() => {
    const list = (all || []).filter((t) => t.kind === 'series')
    const maxYear = list.reduce((m, t) => Math.max(m, parseInt(t.year, 10) || 0), 0)
    return list.filter((t) => parseInt(t.year, 10) === maxYear).slice(0, 8)
  }, [all])

  if (loading) return <div className="page-pad" style={{ minHeight: '100vh' }} />

  return (
    <div style={{ minHeight: '100vh' }}>
      <Header />
      <div style={{ padding: '90px 4vw 40px' }}>
        <h1 style={{ fontSize: 2.2, margin: '0 0 18px' }}>New on Netflix</h1>
        <Top10Rail title="Top 10 TV Shows in the U.S. Today" items={top10Series} />
        <Top10Rail title="Top 10 Movies in the U.S. Today" items={top10Movies} />
        <ComingThisWeek items={coming} />
      </div>
    </div>
  )
}
