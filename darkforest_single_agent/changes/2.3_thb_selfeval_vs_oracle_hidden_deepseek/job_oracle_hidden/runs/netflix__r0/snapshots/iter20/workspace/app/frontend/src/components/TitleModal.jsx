import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { AssetIcon } from '../icons'
import { formatDuration, languageName } from '../utils'
import { RateDialog } from './RateDialog'

export function TitleModal({ titleId, onClose }) {
  const { authFetch } = useAuth()
  const navigate = useNavigate()
  const [title, setTitle] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [season, setSeason] = useState(null)
  const [similar, setSimilar] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [rateOpen, setRateOpen] = useState(false)
  const [listBusy, setListBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        const detail = await authFetch(`/api/titles/${titleId}`)
        if (cancelled) return
        setTitle(detail)
        const episodeList = detail.kind === 'series' ? await authFetch(`/api/titles/${titleId}/episodes`) : []
        if (cancelled) return
        setEpisodes(episodeList)
        setSeason(episodeList[0]?.season || null)
        if (detail.genres?.length) {
          const related = await authFetch(`/api/titles?genre=${encodeURIComponent(detail.genres[0])}&limit=9`)
          if (!cancelled) setSimilar(related.filter((item) => item.id !== detail.id).slice(0, 8))
        } else {
          setSimilar([])
        }
      } catch (requestError) {
        if (!cancelled) setError(requestError.message || 'Could not load this title.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [authFetch, titleId])

  useEffect(() => {
    const onKeyDown = (event) => { if (event.key === 'Escape') onClose() }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose])

  const seasons = useMemo(() => [...new Set(episodes.map((episode) => episode.season))].sort((a, b) => a - b), [episodes])
  const visibleEpisodes = useMemo(
    () => episodes.filter((episode) => season === null || episode.season === season),
    [episodes, season],
  )

  const toggleList = async () => {
    if (!title || listBusy) return
    setListBusy(true)
    setMessage('')
    try {
      if (title.in_my_list) {
        await authFetch(`/api/my-list/${title.id}`, { method: 'DELETE' })
        setTitle((current) => ({ ...current, in_my_list: false }))
        setMessage('Removed from My List')
      } else {
        await authFetch('/api/my-list', { method: 'POST', body: { title_id: title.id } })
        setTitle((current) => ({ ...current, in_my_list: true }))
        setMessage('Added to My List')
      }
    } catch (requestError) {
      setMessage(requestError.message || 'Could not update My List.')
    } finally {
      setListBusy(false)
    }
  }

  const play = () => navigate(`/watch/${title.id}`)
  const openEpisode = (episode) => navigate(`/watch/${title.id}?episode=${episode.id}`)

  return (
    <div className="modal-backdrop title-modal-backdrop" onClick={onClose}>
      <div className="title-modal" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="title-modal-heading">
        <button className="modal-close" onClick={onClose} aria-label="Close title details">
          <AssetIcon name="close" size={26} />
        </button>
        {loading ? (
          <div className="title-modal-loading">
            <span className="loading-ring" />
            <p>Loading title details…</p>
          </div>
        ) : error ? (
          <div className="title-modal-loading">
            <h2>Something went wrong</h2>
            <p>{error}</p>
            <button className="button button-white" onClick={onClose}>Close</button>
          </div>
        ) : title ? (
          <>
            <div className="title-modal-hero" style={{ '--modal-image': `url(${title.backdrop || title.poster})` }}>
              <div className="title-modal-hero-image" />
              <div className="title-modal-hero-shade" />
              <div className="title-modal-hero-copy">
                <h2 id="title-modal-heading">{title.name}</h2>
                <div className="title-modal-actions">
                  <button className="button button-white" onClick={play}>
                    <AssetIcon name="play" size={22} />
                    Play
                  </button>
                  <button
                    className={`round-action modal-round ${title.in_my_list ? 'active' : ''}`}
                    onClick={toggleList}
                    disabled={listBusy}
                    aria-label={title.in_my_list ? 'Remove from My List' : 'Add to My List'}
                  >
                    {title.in_my_list ? <span className="check-glyph">✓</span> : <AssetIcon name="plus" size={22} />}
                  </button>
                  <button className="round-action modal-round" onClick={() => setRateOpen(true)} aria-label="Rate this title">
                    <AssetIcon name={title.my_rating === -1 ? 'thumbs_down' : 'thumbs_up'} size={22} />
                  </button>
                </div>
                {message ? <p className="modal-message">{message}</p> : null}
              </div>
            </div>
            <div className="title-modal-body">
              <div className="title-modal-main">
                <div className="title-modal-meta">
                  <span className="match-score">{Number(title.rating || 0).toFixed(1)} rating</span>
                  <span>{title.year}</span>
                  <span>{title.kind === 'series' ? `${seasons.length || 1} Season${seasons.length === 1 ? '' : 's'}` : formatDuration(title.duration)}</span>
                  <span className="maturity-badge">{title.maturity_rating}</span>
                  <span className="hd-label">HD</span>
                </div>
                <p className="title-modal-synopsis">{title.synopsis}</p>
              </div>
              <aside className="title-modal-aside">
                <p><span>Genres</span> {(title.genres || []).join(', ') || '—'}</p>
                <p><span>Audio</span> {languageName(title.language)} [Original]</p>
                <p><span>Cast</span> Cast information is not available for this title.</p>
              </aside>
            </div>
            {title.kind === 'series' && episodes.length ? (
              <section className="episodes-section">
                <div className="episodes-heading-row">
                  <h3>Episodes</h3>
                  <select value={season ?? ''} onChange={(event) => setSeason(Number(event.target.value))} aria-label="Select season">
                    {seasons.map((seasonNumber) => (
                      <option key={seasonNumber} value={seasonNumber}>Season {seasonNumber}</option>
                    ))}
                  </select>
                </div>
                <div className="episode-list">
                  {visibleEpisodes.map((episode) => (
                    <button className="episode-row" key={episode.id} onClick={() => openEpisode(episode)}>
                      <span className="episode-number">{episode.number}</span>
                      <span className="episode-thumbnail">
                        <img src={episode.thumbnail} alt="" loading="lazy" />
                        <span className="episode-play"><AssetIcon name="play" size={22} /></span>
                      </span>
                      <span className="episode-copy">
                        <span className="episode-title-line">
                          <strong>{episode.name}</strong>
                          <span>{episode.duration}m</span>
                        </span>
                        <span className="episode-synopsis">{episode.synopsis}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            ) : null}
            {similar.length ? (
              <section className="similar-section">
                <h3>More Like This</h3>
                <div className="similar-grid">
                  {similar.map((item) => (
                    <button
                      key={item.id}
                      className="similar-card"
                      onClick={() => navigate(`/title/${item.id}`, { replace: true })}
                    >
                      <img src={item.backdrop || item.poster} alt="" loading="lazy" />
                      <span className="similar-shade" />
                      <span className="similar-info">
                        <strong>{item.name}</strong>
                        <span>
                          <span className="maturity-badge">{item.maturity_rating}</span>
                          {item.year} · {item.kind === 'series' ? 'Series' : 'Film'}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
      {rateOpen && title ? (
        <RateDialog
          title={title}
          currentValue={title.my_rating}
          onClose={() => setRateOpen(false)}
          onRated={(value) => setTitle((current) => ({ ...current, my_rating: value }))}
        />
      ) : null}
    </div>
  )
}
