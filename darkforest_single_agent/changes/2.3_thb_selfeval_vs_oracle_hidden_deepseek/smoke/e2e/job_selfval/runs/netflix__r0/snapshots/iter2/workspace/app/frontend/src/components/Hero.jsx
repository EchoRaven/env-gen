import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useToast } from '../context/ToastContext'
import Icon from './Icon'

export default function Hero({ title, badge = 'NETFLIX', onMoreInfo, loading = false, className = '' }) {
  const navigate = useNavigate()
  const { notify } = useToast()
  const [inList, setInList] = useState(Boolean(title?.in_my_list))
  const [listId, setListId] = useState(title?.my_list_id || null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setInList(Boolean(title?.in_my_list))
    setListId(title?.my_list_id || null)
  }, [title?.id, title?.in_my_list, title?.my_list_id])

  if (loading) return <section className={`hero hero-loading ${className}`}><span className="hero-shimmer" /></section>
  if (!title) return null

  const toggleList = async () => {
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
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={`hero ${className}`} style={{ '--hero-image': `url(${title.backdrop || title.poster})` }}>
      <div className="hero-vignette" />
      <div className="hero-content">
        <div className="hero-badge"><span className="n-mini">N</span>{badge}</div>
        <h1>{title.name}</h1>
        <div className="hero-meta">
          <span className="match-score">{Math.round((Number(title.rating) || 7) * 10)}% Match</span>
          <span>{title.year}</span>
          <span className="maturity">{title.maturity_rating}</span>
          <span>{title.duration} min</span>
          <span className="hd">HD</span>
          {title.top10_rank ? <span className="top10-chip">TOP 10</span> : null}
        </div>
        <p className="hero-synopsis">{title.synopsis}</p>
        <div className="hero-actions">
          <button className="btn btn-play" onClick={() => navigate(`/watch/${title.id}`)}>
            <Icon name="play" size={24} /> Play
          </button>
          <button className="btn btn-more" onClick={() => onMoreInfo?.(title)}>
            <Icon name="info" size={24} /> More Info
          </button>
          <button className={`hero-list-btn ${inList ? 'active' : ''}`} onClick={toggleList} disabled={saving} aria-label={inList ? 'Remove from My List' : 'Add to My List'}>
            <Icon name={inList ? 'check' : 'plus'} size={22} />
          </button>
        </div>
      </div>
      <div className="hero-side-label"><span>{title.kind === 'series' ? 'SERIES' : 'FILM'}</span></div>
      <div className="hero-fade" />
    </section>
  )
}
