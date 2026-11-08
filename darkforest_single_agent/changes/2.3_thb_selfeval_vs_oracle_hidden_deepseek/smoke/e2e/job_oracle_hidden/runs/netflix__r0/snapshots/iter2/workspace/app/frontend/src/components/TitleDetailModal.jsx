import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, assetUrl } from '../api'
import { useApp } from '../context'
import Avatar from './Avatar'
import Icon from './Icon'

function RateDialog({ rating, onRate, onClose }) {
  const options = [
    [-1, 'thumbs-down', 'Not for me'],
    [1, 'thumbs-up', 'I like this'],
    [2, 'thumbs-up-two', 'Love this!'],
  ]
  return (
    <div className="rate-dialog" role="dialog" aria-label="Rate for better recommendations">
      <div className="rate-head">
        <h3>Rate for better recommendations</h3>
        <button className="icon-button" onClick={onClose} aria-label="Close rating dialog"><Icon name="close" size={22} /></button>
      </div>
      <div className="rate-options">
        {options.map(([value, icon, label]) => (
          <button
            key={value}
            className={rating === value ? 'active' : ''}
            onClick={() => onRate(value)}
            aria-label={label}
          >
            <Icon name={icon} size={30} />
            <span>{label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export default function TitleDetailModal({ titleId, onClose }) {
  const navigate = useNavigate()
  const { profile } = useApp()
  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [season, setSeason] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showRate, setShowRate] = useState(false)
  const [busy, setBusy] = useState(false)
  const [related, setRelated] = useState([])

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [detail, eps] = await Promise.all([
        api(`/api/titles/${titleId}`),
        api(`/api/titles/${titleId}/episodes`),
      ])
      setTitle(detail)
      setEpisodes(eps)
      const seasons = [...new Set(eps.map(item => item.season))]
      setSeason(seasons[0] || 1)
      if (detail.genres?.length) {
        const candidates = await api(`/api/titles?genre=${encodeURIComponent(detail.genres[0])}&limit=14`)
        setRelated(candidates.filter(item => item.id !== detail.id).slice(0, 10))
      }
    } catch (err) {
      setError(err.message || 'Could not load this title.')
    } finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [titleId])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') {
        if (showRate) setShowRate(false)
        else onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [onClose, showRate])

  const seasons = useMemo(() => [...new Set(episodes.map(item => item.season))], [episodes])
  const visibleEpisodes = episodes.filter(item => item.season === season)

  const toggleList = async () => {
    if (!title || busy) return
    setBusy(true)
    try {
      if (title.is_in_my_list) {
        await api(`/api/my-list/${title.id}`, { method: 'DELETE' })
        setTitle(value => ({ ...value, is_in_my_list: false, in_my_list: false }))
      } else {
        await api('/api/my-list', { method: 'POST', body: { title_id: title.id } })
        setTitle(value => ({ ...value, is_in_my_list: true, in_my_list: true }))
      }
    } catch (err) { console.error(err) }
    finally { setBusy(false) }
  }

  const setRating = async (value) => {
    if (!title) return
    try {
      const result = await api(`/api/titles/${title.id}/rating`, { method: 'POST', body: { value } })
      setTitle(current => ({ ...current, my_rating: result.value }))
      setShowRate(false)
    } catch (err) { console.error(err) }
  }

  const play = (episodeId) => {
    onClose()
    navigate(`/watch/${titleId}${episodeId ? `?episode=${episodeId}` : ''}`)
  }

  if (loading) {
    return (
      <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
        <div className="title-modal loading-modal"><div className="modal-spinner" /> Loading title…</div>
      </div>
    )
  }
  if (error || !title) {
    return (
      <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
        <div className="title-modal error-modal">
          <h2>Title unavailable</h2>
          <p>{error || 'This title could not be found.'}</p>
          <button className="btn btn-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    )
  }

  return (
    <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <div className="title-modal" role="dialog" aria-modal="true" aria-label={`${title.name} details`}>
        <button className="modal-close icon-button" onClick={onClose} aria-label="Close title details">
          <Icon name="close" size={26} />
        </button>
        <div className="modal-hero">
          <img src={assetUrl(title.backdrop || title.poster)} alt="" />
          <div className="modal-hero-fade" />
          <div className="modal-hero-copy">
            <div className="modal-title-label">{title.kind === 'series' ? 'SERIES' : 'FILM'}</div>
            <h1>{title.name}</h1>
            <div className="modal-buttons">
              <button className="btn btn-play" onClick={() => play()}>
                <Icon name="play" size={21} /> Play
              </button>
              <button className={`round-button modal-round ${title.is_in_my_list ? 'selected' : ''}`} onClick={toggleList} disabled={busy} aria-label={title.is_in_my_list ? 'Remove from My List' : 'Add to My List'}>
                <Icon name={title.is_in_my_list ? 'check' : 'plus'} size={21} />
              </button>
              <button className={`round-button modal-round ${title.my_rating ? 'selected' : ''}`} onClick={() => setShowRate(true)} aria-label="Rate this title">
                <Icon name="thumbs-up" size={20} />
              </button>
              <button className="round-button modal-round" onClick={() => setShowRate(true)} aria-label="Rate for better recommendations">
                <Icon name="thumbs-down" size={20} />
              </button>
            </div>
          </div>
        </div>
        <div className="modal-body">
          <div className="modal-main">
            <div className="modal-meta">
              <span className="match">{Math.max(72, Math.round((title.rating || 6) * 10))}% Match</span>
              <span>{title.year}</span>
              <span className="maturity-badge">{title.maturity_rating}</span>
              <span>{title.kind === 'series' ? `${title.seasons || 1} Season${title.seasons === 1 ? '' : 's'}` : title.duration_label}</span>
              <span className="hd">HD</span>
            </div>
            <p className="modal-synopsis">{title.synopsis || 'Synopsis unavailable.'}</p>
          </div>
          <div className="modal-side">
            <p><span>Genres:</span> {title.genres?.length ? title.genres.join(', ') : '—'}</p>
            <p><span>Cast:</span> Cast information is not available.</p>
            <p><span>This title is:</span> {title.kind === 'series' ? 'Series' : 'Movie'}</p>
          </div>
        </div>

        {episodes.length > 0 && (
          <div className="modal-episodes">
            <div className="episodes-heading">
              <h2>Episodes</h2>
              <select value={season} onChange={event => setSeason(Number(event.target.value))} aria-label="Select season">
                {seasons.map(item => <option value={item} key={item}>Season {item}</option>)}
              </select>
            </div>
            <div className="episode-list">
              {visibleEpisodes.map((episode, index) => (
                <button className="episode" key={episode.id} onClick={() => play(episode.id)}>
                  <span className="episode-index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="episode-thumb">
                    <img src={assetUrl(episode.thumbnail || title.backdrop || title.poster)} alt="" />
                    <span className="episode-play"><Icon name="play" size={21} /></span>
                  </span>
                  <span className="episode-copy">
                    <span className="episode-title-row"><strong>{episode.name}</strong><em>{episode.duration_label}</em></span>
                    <span className="episode-synopsis">{episode.synopsis || 'Episode synopsis unavailable.'}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {related.length > 0 && (
          <div className="modal-related">
            <h2>More Like This</h2>
            <div className="related-grid">
              {related.map(item => (
                <button key={item.id} className="related-card" onClick={() => {
                  const event = new CustomEvent('netflix:open-title', { detail: item.id })
                  window.dispatchEvent(event)
                }}>
                  <img src={assetUrl(item.poster)} alt={item.name} />
                  <span className="related-info">
                    <span className="related-meta"><span className="match">{Math.max(72, Math.round((item.rating || 6) * 10))}% Match</span><span className="maturity-badge">{item.maturity_rating}</span></span>
                    <strong>{item.name}</strong>
                    <span className="related-desc">{item.synopsis || 'Synopsis unavailable.'}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        {showRate && <RateDialog rating={title.my_rating} onRate={setRating} onClose={() => setShowRate(false)} />}
        <div className="modal-profile-note"><Avatar profile={profile} size={26} /> Ratings and My List are saved to {profile?.name || 'this profile'}.</div>
      </div>
    </div>
  )
}
