import { useRef, useState } from 'react'
import Icon from './Icon.jsx'
import TitleCard from './TitleCard.jsx'

export default function PosterRail({ title, items = [], onOpen, variant = 'poster', showEmpty = false, linkTo, progress = false }) {
  const scroller = useRef(null)
  const [hovered, setHovered] = useState(false)
  const visible = items.filter(Boolean)
  if (!visible.length && !showEmpty) return null

  function scroll(direction) {
    const el = scroller.current
    if (!el) return
    el.scrollBy({ left: direction * Math.max(320, el.clientWidth * 0.78), behavior: 'smooth' })
  }

  return (
    <section className={`rail ${variant}`} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
      <div className="rail-heading">
        <h2>{title}</h2>
        {linkTo && <span className="rail-explore">Explore All <Icon name="chevron-right" size={14} /></span>}
      </div>
      <div className={`rail-shell ${variant}`}>
        <button type="button" className={`rail-arrow left ${hovered ? 'visible' : ''}`} onClick={() => scroll(-1)} aria-label={`Scroll ${title} left`}><Icon name="chevron-left" size={28} /></button>
        <div className="rail-scroller" ref={scroller}>
          {!visible.length && <div className="rail-empty">No titles are available in this category yet.</div>}
          {visible.map((item, index) => (
            <TitleCard
              key={item.id}
              item={item}
              onOpen={onOpen}
              top10Rank={variant === 'top10' ? index + 1 : null}
              showProgress={progress}
            />
          ))}
        </div>
        <button type="button" className={`rail-arrow right ${hovered ? 'visible' : ''}`} onClick={() => scroll(1)} aria-label={`Scroll ${title} right`}><Icon name="chevron-right" size={28} /></button>
      </div>
    </section>
  )
}
