import TitleCard from './TitleCard.jsx'

export default function PosterGrid({ items = [], onOpen, emptyTitle = 'Nothing here yet', emptyText = 'There are no titles to show in this category.' }) {
  if (!items.length) {
    return (
      <div className="poster-grid-empty">
        <h3>{emptyTitle}</h3>
        <p>{emptyText}</p>
      </div>
    )
  }
  return (
    <div className="poster-grid">
      {items.map((item) => <TitleCard key={item.id} item={item} onOpen={onOpen} noPreview />)}
    </div>
  )
}
