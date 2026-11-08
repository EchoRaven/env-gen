import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useToast } from '../context/ToastContext'
import Icon from './Icon'
import RateDialog from './RateDialog'
import Spinner from './Spinner'

export default function TitleModal({ titleId, initialTitle, onClose, onChanged }) {
  const [title, setTitle] = useState(initialTitle || null)
  const [episodes, setEpisodes] = useState([])
  const [season, setSeason] = useState(1)
  const [loading, setLoading] = useState(true)
  const [episodesLoading, setEpisodesLoading] = useState(true)
  const [error, setError] = useState('')
  const [rateOpen, setRateOpen] = useState(false)
  const [savingList, setSavingList] = useState(false)
  const navigate = useNavigate()
  const { notify } = useToast()

  useEffect(() => {
    if (!titleId) return undefined
    let active = true
    setLoading(true)
    setError('')
    api.get(`/api/titles/${titleId}`)
      .then((data) => { if (active) setTitle(data.item) })
      .catch((err) => { if (active) setError(err.message) })
      .finally(() => { if (active) setLoading(false) })
    setEpisodesLoading(true)
    api.get(`/api/titles/${titleId}/episodes`)
      .then((data) => {
        if (!active) return
        const items = data.items || []
        setEpisodes(items)
        if (items.length) setSeason(items[0].season)
      })
      .catch(() => { if (active) setEpisodes([]) })
      .finally(() => { if (active) setEpisodesLoading(false) })
    return () => { active = false }
  }, [titleId])

  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event) => { if (event.key === 'Escape' && !rateOpen) onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previous
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose, rateOpen])

  const seasons = useMemo(() => [...new Set(episodes.map((episode) => episode.season))].sort((a, b) => a - b), [episodes])
  const seasonEpisodes = episodes.filter((episode) => episode.season === season)

  if (!titleId) return null

  const toggleList = async () => {
    if (!title || savingList) return
    setSavingList(true)
    try {
      if (title.in_my_list && title.my_list_id) {
        await api.delete(`/api/my-list/${title.my_list_id}`)
        setTitle((current) => ({ ...current, in_my_list: false, my_list_id: null }))
        notify(`Removed ${title.name} from My List.`)
      } else {
        const data = await api.post('/api/my-list', { title_id: title.id })
        setTitle((current) => ({ ...current, in_my_list: true, my_list_id: data.id || data.item?.my_list_id }))
        notify(`Added ${title.name} to My List.`, 'success')
      }
      onChanged?.()
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setSavingList(false)
    }
  }

  const playEpisode = (episode) => {
    const suffix = episode ? `?episode=${episode.id}` : ''
    navigate(`/watch/${title.id}${suffix}`)
  }

  const ratingLabels = { '-1': 'Not for me', 1: 'I like this', 2: 'Love this!' }

  return (
    <div className="modal-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget && !rateOpen) onClose?.() }}>
      <section className="title-modal" role="dialog" aria-modal="true" aria-label={title ? `${title.name} details` : 'Title details'}>
        <button className="modal-close icon-btn" onClick={onClose} aria-label="Close details"><Icon name="close" size={26} /></button>
        {loading && !title ? <div className="modal-loading"><Spinner /></div> : null}
        {error && !title ? (
          <div className="modal-loading">
            <p>{error}</p>
            <button className="btn btn-light" onClick={onClose}>Close</button>
          </div>
        ) : null}
        {title ? (
          <>
            <div className="modal-hero" style={{ backgroundImage: `url(${title.backdrop || title.poster})` }}>
              <div className="modal-hero-gradient" />
              <div className="modal-hero-content">
                <p className="detail-kicker">{title.kind === 'series' ? 'N SERIES' : 'N FILM'}</p>
                <h2>{title.name}</h2>
                <div className="modal-actions">
                  <button className="btn btn-play" onClick={() => playEpisode(seasonEpisodes[0])}>
                    <Icon name="play" size={24} /> Play
                  </button>
                  <button className={`round-action modal-round ${title.in_my_list ? 'active' : ''}`} onClick={toggleList} disabled={savingList} aria-label={title.in_my_list ? 'Remove from My List' : 'Add to My List'} title={title.in_my_list ? 'Remove from My List' : 'Add to My List'}>
                    <Icon name={title.in_my_list ? 'check' : 'plus'} size={23} />
                  </button>
                  <button className={`round-action modal-round ${title.profile_rating ? 'active' : ''}`} onClick={() => setRateOpen(true)} aria-label="Rate this title" title="Rate this title">
                    <Icon name="thumbUp" size={22} />
                  </button>
                </div>
              </div>
            </div>
            <div className="modal-body">
              <div className="modal-primary">
                <div className="detail-meta">
                  <span className="match-score">{Math.round((Number(title.rating) || 7) * 10)}% Match</span>
                  <span>{title.year}</span>
                  <span className="maturity">{title.maturity_rating}</span>
                  <span>{title.duration} min</span>
                  <span className="hd">HD</span>
                </div>
                <p className="modal-synopsis">{title.synopsis}</p>
              </div>
              <div className="modal-secondary">
                <p><span className="muted-label">Genres:</span> {(title.genres || [title.genre]).join(', ')}</p>
                <p><span className="muted-label">This title is:</span> {(title.genres || [title.genre]).slice(0, 2).join(', ')}</p>
                <p><span className="muted-label">Maturity rating:</span> <span className="maturity">{title.maturity_rating}</span> Recommended for ages 14 and up</p>
                {title.profile_rating ? <p><span className="muted-label">Your rating:</span> {ratingLabels[title.profile_rating]}</p> : null}
              </div>
            </div>

            {title.kind === 'series' ? (
              <div className="episodes-section">
                <div className="episodes-heading">
                  <h3>Episodes</h3>
                  {seasons.length > 1 ? (
                    <label className="season-select">
                      <span className="sr-only">Choose a season</span>
                      <select value={season} onChange={(event) => setSeason(Number(event.target.value))}>
                        {seasons.map((number) => <option key={number} value={number}>Season {number}</option>)}
                      </select>
                      <Icon name="chevronDown" size={16} />
                    </label>
                  ) : <span className="season-static">Season {season}</span>}
                </div>
                {episodesLoading ? <Spinner label="Loading episodes…" /> : seasonEpisodes.length ? (
                  <div className="episode-list">
                    {seasonEpisodes.map((episode, index) => (
                      <button key={episode.id} className="episode-row" onClick={() => playEpisode(episode)}>
                        <span className="episode-number">{String(index + 1).padStart(2, '0')}</span>
                        <span className="episode-thumb">
                          <img src={episode.thumbnail} alt="" loading="lazy" />
                          <span className="episode-play"><Icon name="play" size={22} /></span>
                        </span>
                        <span className="episode-copy">
                          <span className="episode-title"><strong>{episode.name}</strong><span>{episode.duration}m</span></span>
                          <span className="episode-synopsis">{episode.synopsis}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                ) : <p className="rail-empty">Episodes are not available for this title.</p>}
              </div>
            ) : null}

            <div className="modal-about">
              <h3>About <span>{title.name}</span></h3>
              <p><span className="muted-label">Genres</span>{(title.genres || [title.genre]).join(', ')}</p>
              <p><span className="muted-label">Maturity rating</span>{title.maturity_rating} · Some material may be unsuitable for children under 14.</p>
              <p><span className="muted-label">Audio</span>English · Stereo</p>
              <p><span className="muted-label">Subtitles</span>English</p>
            </div>
          </>
        ) : null}
      </section>
      {rateOpen && title ? (
        <RateDialog
          title={title}
          initialValue={title.profile_rating}
          onClose={() => setRateOpen(false)}
          onRated={(value) => {
            setTitle((current) => ({ ...current, profile_rating: value }))
            onChanged?.()
          }}
        />
      ) : null}
    </div>
  )
}
