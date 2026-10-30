import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Icon from './Icon';
import { ListButton, rateIcon } from './TitleCard';
import { API } from '../api';
import { useStore } from '../store';
import { LANGUAGES, fmtDuration, lengthLabel } from '../utils';

const RATE_CHOICES = [
  [-1, 'nf-thumbs_down', 'We won’t suggest this to you again', 'Not for me'],
  [1, 'nf-thumbs_up', 'We’ll show you more like this', 'I like this'],
  [2, 'nf-thumbs_up_two', 'We know you’re a true fan!', 'Love this!'],
];

export function RateDialog({ title, onClose }) {
  const { ratings, rate } = useStore();
  const current = ratings[title.id];
  const [busy, setBusy] = useState(false);
  return (
    <div className="rate-dialog-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label="Rate for better recommendations">
      <div className="rate-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="rd-line" />
        <button className="rd-close" aria-label="Close rating dialog" onClick={onClose}><Icon name="nf-close" size={36} /></button>
        <h2>Rate for better recommendations</h2>
        <p>Your feedback helps us show you more of what you like (and love!).</p>
        <div className="rd-options">
          {RATE_CHOICES.map(([v, icon, text, label]) => (
            <button
              key={v}
              className={`rd-opt ${current === v ? 'selected' : ''}`}
              aria-label={label}
              aria-pressed={current === v}
              disabled={busy}
              onClick={async () => { setBusy(true); try { await rate(title, v); } finally { setBusy(false); } }}
            >
              <Icon name={icon} size={56} />
              <span>{text}</span>
            </button>
          ))}
        </div>
        <button className="rd-got" onClick={onClose}>Got it!</button>
      </div>
    </div>
  );
}

function SeasonSelect({ seasons, value, onChange }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="season-select">
      <button className="season-btn" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}>
        Season {value} <span className="tri" />
      </button>
      {open && (
        <ul className="season-menu" role="listbox">
          {seasons.map((s) => (
            <li key={s}>
              <button role="option" aria-selected={s === value} onClick={() => { onChange(s); setOpen(false); }}>
                Season {s}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MoreLikeThis({ title }) {
  const [items, setItems] = useState(null);
  const navigate = useNavigate();
  const [, setParams] = useSearchParams();
  useEffect(() => {
    let alive = true;
    API.titles({ genre: title.genre, limit: 13 })
      .then((r) => alive && setItems(r.filter((t) => t.id !== title.id).slice(0, 9)))
      .catch(() => alive && setItems([]));
    return () => { alive = false; };
  }, [title.id, title.genre]);
  if (!items) return null;
  return (
    <section className="more-like">
      <h3>More Like This</h3>
      {items.length === 0 ? <p className="muted">—</p> : (
        <div className="ml-grid">
          {items.map((t) => (
            <div key={t.id} className="ml-card">
              <button className="ml-media" onClick={() => setParams((p) => { p.set('title', t.id); return p; })} aria-label={`Open ${t.name}`}>
                <img src={t.backdrop || t.poster} alt="" loading="lazy" />
                <span className="ml-len">{lengthLabel(t)}</span>
                <span className="ml-play" onClick={(e) => { e.stopPropagation(); navigate(`/watch/${t.id}`); }} role="button" aria-label={`Play ${t.name}`}>
                  <Icon name="nf-play" size={22} />
                </span>
              </button>
              <div className="ml-body">
                <div className="ml-row">
                  <div>
                    <div className="ml-name">{t.name}</div>
                    <div className="ml-meta"><span className="maturity">{t.maturity_rating}</span> <span className="hd">HD</span> {t.year}</div>
                  </div>
                  <ListButton title={t} />
                </div>
                <p>{t.synopsis}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function TitleModal({ id, onClose }) {
  const navigate = useNavigate();
  const { ratings } = useStore();
  const [title, setTitle] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [season, setSeason] = useState(1);
  const [error, setError] = useState(null);
  const [rateOpen, setRateOpen] = useState(false);
  const [muted, setMuted] = useState(true);
  const [videoOn, setVideoOn] = useState(false);
  const videoRef = useRef(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    let alive = true;
    setTitle(null); setEpisodes([]); setError(null); setVideoOn(false);
    API.title(id).then((t) => {
      if (!alive) return;
      setTitle(t);
      if (t.kind === 'series') API.episodes(id).then((e) => alive && setEpisodes(e)).catch(() => {});
    }).catch((e) => alive && setError(e.message));
    scrollRef.current?.scrollTo(0, 0);
    const timer = setTimeout(() => alive && setVideoOn(true), 1800);
    return () => { alive = false; clearTimeout(timer); };
  }, [id]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !rateOpen) onClose(); };
    document.addEventListener('keydown', onKey);
    document.body.classList.add('modal-open');
    return () => { document.removeEventListener('keydown', onKey); document.body.classList.remove('modal-open'); };
  }, [onClose, rateOpen]);

  useEffect(() => { if (videoRef.current) videoRef.current.muted = muted; }, [muted, videoOn]);

  const seasons = [...new Set(episodes.map((e) => e.season))];
  const seasonEps = episodes.filter((e) => e.season === season);
  const rating = title ? ratings[title.id] : undefined;
  const resumeEp = title?.resume_episode_id ? episodes.find((e) => e.id === title.resume_episode_id) : null;

  return (
    <div className="modal-backdrop" onClick={onClose} ref={scrollRef} data-testid="title-modal">
      <div className="title-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title?.name || 'Title details'}>
        <button className="modal-close" aria-label="Close" onClick={onClose}><Icon name="nf-close" size={22} /></button>
        {error && <div className="modal-error">{error}</div>}
        {!title && !error && <div className="modal-loading"><div className="spinner" /></div>}
        {title && (
          <>
            <div className="tm-hero">
              <img src={title.backdrop || title.poster} alt="" />
              {videoOn && title.video_url && (
                <video ref={videoRef} src={title.video_url} autoPlay muted={muted} playsInline onEnded={() => setVideoOn(false)} onError={() => setVideoOn(false)} />
              )}
              <div className="tm-shade" />
              <div className="tm-hero-content">
                <h2 className="tm-title">{title.name}</h2>
                <div className="tm-buttons">
                  <button className="btn btn-play" onClick={() => navigate(`/watch/${title.id}${resumeEp ? `?ep=${resumeEp.id}` : ''}`)}>
                    <Icon name="nf-play" size={30} /> {title.progress_seconds > 0 ? 'Resume' : 'Play'}
                  </button>
                  <ListButton title={title} size="lg" />
                  <button className={`circle-btn lg ${rating ? 'rated' : ''}`} aria-label="Rate this title" onClick={() => setRateOpen(true)}>
                    <Icon name={rateIcon(rating)} size={24} />
                  </button>
                </div>
                <button className="circle-btn lg tm-mute" aria-label={muted ? 'Unmute' : 'Mute'} onClick={() => { setVideoOn(true); setMuted((m) => !m); }}>
                  <Icon name={muted ? 'nf-volume_off' : 'nf-volume_high'} size={20} />
                </button>
              </div>
            </div>
            <div className="tm-body">
              <div className="tm-info">
                <div className="tm-left">
                  <div className="tm-meta">
                    <span>{title.year}</span>
                    <span>{lengthLabel(title)}</span>
                    <span className="hd">HD</span>
                    <Icon name="nf-subtitles" size={18} />
                  </div>
                  <div className="tm-meta2">
                    <span className="maturity">{title.maturity_rating}</span>
                    <span>{title.genres.join(', ').toLowerCase()}</span>
                  </div>
                  {title.top10_rank && (
                    <div className="tm-rank"><span className="top10-badge big"><small>TOP</small>10</span> #{title.top10_rank} in {title.kind === 'series' ? 'TV Shows' : 'Movies'} Today</div>
                  )}
                  <p className="tm-synopsis">{title.synopsis}</p>
                </div>
                <div className="tm-right">
                  <p><span className="muted">Cast: </span>—</p>
                  <p><span className="muted">Genres: </span>{title.genres.join(', ')}</p>
                  <p><span className="muted">Original Language: </span>{LANGUAGES[title.language] || title.language || '—'}</p>
                  <p><span className="muted">Rating: </span>{title.rating != null ? `${title.rating.toFixed(1)} / 10` : '—'}</p>
                </div>
              </div>

              {title.kind === 'series' && (
                <section className="episodes">
                  <div className="ep-head">
                    <h3>Episodes</h3>
                    {seasons.length > 1 ? <SeasonSelect seasons={seasons} value={season} onChange={setSeason} /> : <span className="ep-series">{title.name}</span>}
                  </div>
                  {seasons.length > 1 && (
                    <div className="ep-season-meta">Season {season}: <span className="maturity">{title.maturity_rating}</span> {title.genres.join(', ').toLowerCase()}</div>
                  )}
                  {episodes.length === 0 && <p className="muted">—</p>}
                  {seasonEps.map((ep) => (
                    <button key={ep.id} className={`episode ${resumeEp?.id === ep.id ? 'current' : ''}`} onClick={() => navigate(`/watch/${title.id}?ep=${ep.id}`)}>
                      <span className="ep-num">{ep.number}</span>
                      <span className="ep-thumb">
                        <img src={ep.thumbnail} alt="" loading="lazy" />
                        <span className="ep-play"><Icon name="nf-play" size={22} /></span>
                      </span>
                      <span className="ep-body">
                        <span className="ep-title"><b>{ep.name}</b><span>{fmtDuration(ep.duration)}</span></span>
                        <span className="ep-syn">{ep.synopsis}</span>
                      </span>
                    </button>
                  ))}
                </section>
              )}

              <MoreLikeThis title={title} />

              <section className="about">
                <h3>About <b>{title.name}</b></h3>
                <p><span className="muted">Cast: </span>—</p>
                <p><span className="muted">Genres: </span>{title.genres.join(', ')}</p>
                <p><span className="muted">Maturity Rating: </span><span className="maturity">{title.maturity_rating}</span></p>
              </section>
            </div>
            {rateOpen && <RateDialog title={title} onClose={() => setRateOpen(false)} />}
          </>
        )}
      </div>
    </div>
  );
}
