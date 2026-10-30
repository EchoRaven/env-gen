import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Icon from './Icon';
import { useOpenTitle } from './TitleCard';
import { lengthLabel } from '../utils';

// Hero billboard: backdrop art, then the title's clip fades in (muted) after a moment.
export default function Billboard({ title, variant = 'inset', playLabel = 'Play' }) {
  const navigate = useNavigate();
  const openTitle = useOpenTitle();
  const videoRef = useRef(null);
  const [muted, setMuted] = useState(true);
  const [showVideo, setShowVideo] = useState(false);

  useEffect(() => {
    setShowVideo(false);
    if (!title?.video_url) return undefined;
    const t = setTimeout(() => setShowVideo(true), 2500);
    return () => clearTimeout(t);
  }, [title?.id, title?.video_url]);

  useEffect(() => { if (videoRef.current) videoRef.current.muted = muted; }, [muted, showVideo]);

  if (!title) return <div className={`billboard ${variant} skeleton`} />;
  const toggleMute = () => {
    if (!showVideo) setShowVideo(true);
    setMuted((m) => !m);
  };
  return (
    <section className={`billboard ${variant}`} data-testid="billboard">
      <div className="bb-media">
        <img src={title.backdrop || title.poster} alt="" />
        {showVideo && (
          <video
            ref={videoRef}
            src={title.video_url}
            autoPlay
            muted={muted}
            playsInline
            onEnded={() => setShowVideo(false)}
            onError={() => setShowVideo(false)}
          />
        )}
        <div className="bb-shade" />
      </div>
      <div className="bb-content">
        {variant !== 'inset' && <img className="bb-netflix" src="/assets/brand/netflix_wordmark.svg" alt="" />}
        <h1 className="bb-title">{title.name}</h1>
        {title.top10_rank ? (
          <div className="bb-rank">
            <span className="top10-badge big"><small>TOP</small>10</span>
            #{title.top10_rank} in {title.kind === 'series' ? 'TV Shows' : 'Movies'} Today
          </div>
        ) : null}
        <div className="bb-meta">
          <span>{title.genre}</span><i className="dot" />
          <span>{title.year}</span><i className="dot" />
          <span>{lengthLabel(title)}</span><i className="dot" />
          <span>{title.maturity_rating}</span>
        </div>
        {variant !== 'inset' && <p className="bb-synopsis">{title.synopsis}</p>}
        <div className="bb-buttons">
          <button className="btn btn-play" onClick={() => navigate(`/watch/${title.id}`)}>
            <Icon name="nf-play" size={28} /> {playLabel}
          </button>
          <button className="btn btn-info" onClick={() => openTitle(title.id)}>
            {variant !== 'inset' && <Icon name="info" size={28} />} More Info
          </button>
        </div>
      </div>
      <div className="bb-side">
        <button className="circle-btn bb-mute" aria-label={muted ? 'Unmute preview' : 'Mute preview'} onClick={toggleMute}>
          <Icon name={muted ? 'nf-volume_off' : 'nf-volume_high'} size={18} />
        </button>
        {variant !== 'inset' && <span className="bb-maturity">{title.maturity_rating}</span>}
        {variant === 'inset' && title.year >= 2026 && (
          <span className="bb-new"><Icon name="nf-new_episode" size={22} /> {title.kind === 'series' ? 'New Episodes' : 'Recently Added'}</span>
        )}
      </div>
    </section>
  );
}
