import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useToast } from '../context/ToastContext'
import Icon from './Icon'
import RateDialog from './RateDialog'

export default function TitleCard({
  title,
  rank,
  continueItem = false,
  onOpen,
  onRate,
  onChanged,
  compact = false,
  landscape = false,
}) {
  const [hovered, setHovered] = useState(false)
  const [inList, setInList] = useState(Boolean(title.in_my_list))
  const [listId, setListId] = useState(title.my_list_id || null)
  const [saving, setSaving] = useState(false)
  const [rateOpen, setRateOpen] = useState(false)
  const [profileRating, setProfileRating] = useState(title.profile_rating)
  const navigate = useNavigate()
  const { notify } = useToast()

  useEffect(() => {
    setInList(Boolean(title.in_my_list))
    setListId(title.my_list_id || null)
  }, [title.id, title.in_my_list, title.my_list_id])

  const play = (event) => {
    event?.stopPropagation?.()
    navigate(`/watch/${title.id}`)
  }

  const open = (event) => {
    event?.stopPropagation?.()
    if (onOpen) onOpen(title)
    else navigate(`/title/${title.id}`)
  }

  const toggleList = async (event) => {
    event?.stopPropagation?.()
    if (saving) return
    setSaving(true)
    try {
      if (inList && listId) {
        await api.delete(`/api/my-list/${listId}`)
        setInList(false)
        setListId(null)
        notify(`Removed ${title.name} from My List.`)
      } else {
        const data = await api.post('/api/my-list', { title_id: title.id })
        setInList(true)
        setListId(data.id || data.item?.my_list_id)
        notify(`Added ${title.name} to My List.`, 'success')
      }
      onChanged?.()
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const rate = (event) => {
    event?.stopPropagation?.()
    setRateOpen(true)
    onRate?.(title)
  }

  const progress = continueItem && title.duration
    ? Math.min(100, Number(title.progress_percent) || (title.progress_seconds / (title.duration * 60)) * 100)
    : 0

  return (
    <article
      className={`title-card ${hovered ? 'hovered' : ''} ${compact ? 'compact' : ''} ${landscape ? 'landscape' : ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={open}
      tabIndex={0}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') open(event) }}
      aria-label={`${title.name}, ${title.year}`}
    >
      {rank ? <span className="rank-number" aria-hidden="true">{rank}</span> : null}
      <div className="title-card-art">
        <img className="card-poster" src={landscape ? (title.backdrop || title.poster) : title.poster} alt={title.name} loading="lazy" />
        {landscape ? <span className="card-title-overlay">{title.name}</span> : null}
        <img className="card-hover-backdrop" src={title.backdrop || title.poster} alt="" loading="lazy" />
        <div className="card-hover-shade" />
        <div className="card-hover-info">
          <h3>{title.name}</h3>
          <div className="card-actions">
            <button className="round-action play" onClick={play} aria-label={`Play ${title.name}`}><Icon name="play" size={20} /></button>
            <button className={`round-action ${inList ? 'active' : ''}`} onClick={toggleList} disabled={saving} aria-label={inList ? `Remove ${title.name} from My List` : `Add ${title.name} to My List`}>
              <Icon name={inList ? 'check' : 'plus'} size={20} />
            </button>
            <button className={`round-action ${profileRating ? 'active' : ''}`} onClick={rate} aria-label={`Rate ${title.name}`}><Icon name="thumbUp" size={19} /></button>
            <button className="round-action expand" onClick={open} aria-label={`More information about ${title.name}`}><Icon name="chevronDown" size={20} /></button>
          </div>
          <div className="card-meta">
            <span className="maturity">{title.maturity_rating}</span>
            <span>{title.year}</span>
            <span className="card-duration">{title.duration} min</span>
            <span className="hd">HD</span>
          </div>
          <p className="card-synopsis">{title.synopsis}</p>
          <div className="card-tags">{(title.genres || []).slice(0, 3).map((genre) => <span key={genre}>{genre}</span>)}</div>
        </div>
        {continueItem && progress > 0 ? (
          <div className="card-progress"><span style={{ width: `${progress}%` }} /></div>
        ) : null}
      </div>
      {rateOpen ? (
        <RateDialog
          title={title}
          initialValue={profileRating}
          onClose={() => setRateOpen(false)}
          onRated={(value) => { setProfileRating(value); onChanged?.() }}
        />
      ) : null}
    </article>
  )
}
