import { useRef } from 'react'
import Icon from './Icon'
import TitleCard from './TitleCard'

export default function TitleRail({
  title,
  eyebrow,
  items = [],
  top10 = false,
  continueRail = false,
  emptyMessage = 'Nothing here yet.',
  loading = false,
  onOpen,
  onRate,
  onChanged,
}) {
  const scroller = useRef(null)
  const move = (direction) => {
    const node = scroller.current
    if (!node) return
    node.scrollBy({ left: direction * Math.max(360, node.clientWidth * 0.8), behavior: 'smooth' })
  }

  if (!loading && items.length === 0 && !emptyMessage) return null

  return (
    <section className={`rail ${top10 ? 'top10-rail' : ''}`}>
      <div className="rail-heading">
        <div>
          {eyebrow ? <span className="rail-eyebrow">{eyebrow}</span> : null}
          <h2>{title}</h2>
        </div>
        {items.length > 0 ? (
          <div className="rail-arrows">
            <button className="rail-arrow" onClick={() => move(-1)} aria-label={`Scroll ${title} left`}><Icon name="chevronLeft" size={22} /></button>
            <button className="rail-arrow" onClick={() => move(1)} aria-label={`Scroll ${title} right`}><Icon name="chevronRight" size={22} /></button>
          </div>
        ) : null}
      </div>
      {loading ? (
        <div className="rail-skeletons">{[0, 1, 2, 3, 4, 5].map((n) => <div key={n} className="rail-skeleton" />)}</div>
      ) : items.length ? (
        <div className="rail-scroller" ref={scroller}>
          {items.map((item, index) => (
            <TitleCard
              key={`${item.id}-${index}`}
              title={item}
              rank={top10 ? (item.top10_rank || index + 1) : null}
              continueItem={continueRail}
              landscape
              onOpen={onOpen}
              onRate={onRate}
              onChanged={onChanged}
            />
          ))}
        </div>
      ) : (
        <p className="rail-empty">{emptyMessage}</p>
      )}
    </section>
  )
}
