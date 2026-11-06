import { useRef } from 'react'
import Card from './Card'
import Icon from './Icon'
import { openTitleModal } from '../lib/modalStore'

export default function Rail({ title, items, variant = 'poster', emptyText = 'Nothing here yet.', actions = null }) {
  const scroller = useRef(null)
  const scrollBy = (dir) => {
    const el = scroller.current
    if (!el) return
    el.scrollBy({ left: dir * (el.clientWidth * 0.8), behavior: 'smooth' })
  }

  return (
    <section className="rail">
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <h2 className="rail-title">{title}</h2>
        {actions}
      </div>
      {(!items || items.length === 0) ? (
        <div className="rail-empty">{emptyText}</div>
      ) : (
        <>
          <div className="rail-scroll" ref={scroller}>
            {items.map((t) => (
              <Card key={`${t.id}-${t.top10_rank ?? ''}`} title={t} rank={t.top10_rank} />
            ))}
          </div>
          <button className="rail-nav left" aria-label="Scroll left" onClick={() => scrollBy(-1)}><Icon name="chevron_left" size={34} /></button>
          <button className="rail-nav right" aria-label="Scroll right" onClick={() => scrollBy(1)}><Icon name="chevron_right" size={34} /></button>
        </>
      )}
    </section>
  )
}

// Rail of big ranked numerals (Top 10)
export function Top10Rail({ title, items }) {
  const scroller = useRef(null)
  const scrollBy = (dir) => {
    const el = scroller.current
    if (!el) return
    el.scrollBy({ left: dir * (el.clientWidth * 0.8), behavior: 'smooth' })
  }
  if (!items || items.length === 0) {
    return (
      <section className="rail">
        <h2 className="rail-title">{title}</h2>
        <div className="rail-empty">No ranked titles yet.</div>
      </section>
    )
  }
  return (
    <section className="rail">
      <h2 className="rail-title">{title}</h2>
      <div className="rail-scroll" ref={scroller}>
        {items.map((t, i) => (
          <div
            key={t.id}
            className="top10-card"
            onClick={() => openTitleModal(t.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && openTitleModal(t.id)}
          >
            <span className="num">{i + 1}</span>
            <img className="card-poster" src={t.poster ? requireMedia(t.poster) : ''} alt={t.name} loading="lazy" />
          </div>
        ))}
      </div>
      <button className="rail-nav left" aria-label="Scroll left" onClick={() => scrollBy(-1)}><Icon name="chevron_left" size={34} /></button>
      <button className="rail-nav right" aria-label="Scroll right" onClick={() => scrollBy(1)}><Icon name="chevron_right" size={34} /></button>
    </section>
  )
}

import { mediaUrl as requireMedia } from '../lib/util'
