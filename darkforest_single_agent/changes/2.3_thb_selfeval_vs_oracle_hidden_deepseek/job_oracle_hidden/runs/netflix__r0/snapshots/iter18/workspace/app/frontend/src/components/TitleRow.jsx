import { useRef } from 'react'
import { AssetIcon } from '../icons'
import { TitleCard, Top10Card } from './TitleCard'

export function TitleRow({
  title,
  items = [],
  loading = false,
  numbered = false,
  progressRows = false,
  onOpen,
  onPlay,
  onToggleList,
  onRate,
  emptyMessage = 'This collection is empty.',
}) {
  const railRef = useRef(null)

  const scroll = (direction) => {
    const rail = railRef.current
    if (!rail) return
    rail.scrollBy({ left: direction * Math.max(560, rail.clientWidth * 0.82), behavior: 'smooth' })
  }

  return (
    <section className="title-row" aria-labelledby={`row-${title.replace(/\W+/g, '-').toLowerCase()}`}>
      <div className="row-heading">
        <h2 id={`row-${title.replace(/\W+/g, '-').toLowerCase()}`}>{title}</h2>
        {items.length ? <span className="row-count">{items.length}</span> : null}
      </div>
      <div className="row-shell">
        {items.length > 3 ? (
          <button className="row-arrow row-arrow-left" onClick={() => scroll(-1)} aria-label={`Scroll ${title} left`}>
            <AssetIcon name="arrow_left" size={28} />
          </button>
        ) : null}
        <div className={`row-rail ${numbered ? 'numbered-rail' : ''}`} ref={railRef}>
          {loading
            ? Array.from({ length: 6 }).map((_, index) => (
                <div className="skeleton-card" key={index} aria-hidden="true">
                  <span />
                </div>
              ))
            : items.map((item, index) =>
                numbered ? (
                  <Top10Card key={item.id} title={item} rank={item.top10_rank || index + 1} onOpen={onOpen} />
                ) : (
                  <TitleCard
                    key={item.id}
                    title={item}
                    inList={item.in_my_list}
                    showProgress={progressRows}
                    progressSeconds={item.progress_seconds || 0}
                    index={index}
                    onOpen={onOpen}
                    onPlay={onPlay}
                    onToggleList={onToggleList}
                    onRate={onRate}
                  />
                ),
              )}
          {!loading && items.length === 0 ? <div className="row-empty">{emptyMessage}</div> : null}
        </div>
        {items.length > 3 ? (
          <button className="row-arrow row-arrow-right" onClick={() => scroll(1)} aria-label={`Scroll ${title} right`}>
            <AssetIcon name="arrow_left" size={28} />
          </button>
        ) : null}
      </div>
    </section>
  )
}
