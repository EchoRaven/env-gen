import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Icon from './Icon';
import { useStore } from '../store';
import { badgeFor, lengthLabel } from '../utils';

export function useOpenTitle() {
  const [, setParams] = useSearchParams();
  return (id) => setParams((p) => { p.set('title', id); return p; });
}

const RATE_OPTS = [
  [-1, 'nf-thumbs_down', 'Not for me'],
  [1, 'nf-thumbs_up', 'I like this'],
  [2, 'nf-thumbs_up_two', 'Love this!'],
];

export function rateIcon(v) {
  if (v === -1) return 'nf-thumbs_down';
  if (v >= 2) return 'nf-thumbs_up_two';
  return 'nf-thumbs_up';
}

// Thumbs button that expands into down / up / love on hover (card + modal).
export function RatePicker({ title, size = 'md' }) {
  const { ratings, rate } = useStore();
  const [open, setOpen] = useState(false);
  const [tip, setTip] = useState(null);
  const current = ratings[title.id];
  return (
    <div className={`rate-picker ${size} ${open ? 'open' : ''}`} onMouseLeave={() => { setOpen(false); setTip(null); }}>
      {!open && (
        <button
          className={`circle-btn ${current ? 'rated' : ''}`}
          aria-label={current ? 'Change rating' : 'Rate this title'}
          onMouseEnter={() => setOpen(true)}
          onClick={() => setOpen(true)}
        >
          <Icon name={rateIcon(current)} size={size === 'lg' ? 24 : 20} />
        </button>
      )}
      {open && (
        <div className="rate-options" role="group" aria-label="Rate">
          {tip && <div className="rate-tip">{tip}</div>}
          {RATE_OPTS.map(([v, icon, label]) => (
            <button
              key={v}
              className={`rate-opt ${current === v ? 'selected' : ''}`}
              aria-label={label}
              aria-pressed={current === v}
              onMouseEnter={() => setTip(label)}
              onClick={async (e) => { e.stopPropagation(); await rate(title, v); }}
            >
              <Icon name={icon} size={size === 'lg' ? 24 : 20} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ListButton({ title, size = 'md' }) {
  const { myList, toggleMyList } = useStore();
  const inList = myList.has(title.id);
  return (
    <button
      className={`circle-btn ${size}`}
      aria-label={inList ? 'Remove from My List' : 'Add to My List'}
      title={inList ? 'Remove from My List' : 'Add to My List'}
      onClick={(e) => { e.stopPropagation(); toggleMyList(title); }}
    >
      <Icon name={inList ? 'check' : 'nf-plus'} size={size === 'lg' ? 24 : 20} />
    </button>
  );
}

function Preview({ title, rect, onClose, onEnter }) {
  const navigate = useNavigate();
  const openTitle = useOpenTitle();
  const w = Math.max(rect.width * 1.5, 360);
  let left = rect.left + rect.width / 2 - w / 2;
  left = Math.max(16, Math.min(left, window.innerWidth - w - 16));
  const top = rect.top + window.scrollY - rect.height * 0.25;
  const tags = (title.genres || []).slice(0, 3);
  const [playClip, setPlayClip] = useState(false);
  const [muted, setMuted] = useState(true);
  const videoRef = useRef(null);
  useEffect(() => { const t = setTimeout(() => setPlayClip(true), 700); return () => clearTimeout(t); }, []);
  useEffect(() => { if (videoRef.current) videoRef.current.muted = muted; }, [muted, playClip]);
  return createPortal(
    <div
      className="card-preview"
      style={{ left, top, width: w }}
      onMouseEnter={onEnter}
      onMouseLeave={onClose}
      onClick={() => openTitle(title.id)}
      data-testid="card-preview"
    >
      <div className="cp-media">
        <img src={title.backdrop || title.poster} alt="" />
        {playClip && title.video_url && (
          <video ref={videoRef} src={title.video_url} autoPlay muted={muted} loop playsInline onError={() => setPlayClip(false)} />
        )}
        <button
          className="circle-btn cp-mute"
          aria-label={muted ? 'Unmute preview' : 'Mute preview'}
          onClick={(e) => { e.stopPropagation(); setPlayClip(true); setMuted((m) => !m); }}
        >
          <Icon name={muted ? 'nf-volume_off' : 'nf-volume_high'} size={16} />
        </button>
        <img className="cp-n" src="/assets/brand/netflix_n_icon.svg" alt="" />
        <div className="cp-name">{title.name}</div>
      </div>
      <div className="cp-info" onClick={(e) => e.stopPropagation()}>
        <div className="cp-buttons">
          <button className="circle-btn play" aria-label={`Play ${title.name}`} onClick={() => navigate(`/watch/${title.id}`)}>
            <Icon name="nf-play" size={22} />
          </button>
          <ListButton title={title} />
          <RatePicker title={title} />
          <button className="circle-btn expand" aria-label="More info" onClick={() => { onClose(); openTitle(title.id); }}>
            <Icon name="chevron-down" size={22} />
          </button>
        </div>
        <div className="cp-meta">
          <span className="maturity">{title.maturity_rating}</span>
          <span>{lengthLabel(title)}</span>
          <span className="hd">HD</span>
        </div>
        <div className="cp-tags">
          {tags.map((g, i) => <span key={g}>{i > 0 && <i className="dot" />}{g}</span>)}
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default function TitleCard({ title, variant = 'landscape', rank, progress }) {
  const openTitle = useOpenTitle();
  const ref = useRef(null);
  const timer = useRef(null);
  const leaveTimer = useRef(null);
  const [rect, setRect] = useState(null);

  useEffect(() => () => { clearTimeout(timer.current); clearTimeout(leaveTimer.current); }, []);

  const enter = () => {
    clearTimeout(leaveTimer.current);
    timer.current = setTimeout(() => { if (ref.current) setRect(ref.current.getBoundingClientRect()); }, 450);
  };
  const leave = () => {
    clearTimeout(timer.current);
    leaveTimer.current = setTimeout(() => setRect(null), 120);
  };
  const keepOpen = () => clearTimeout(leaveTimer.current);

  const badge = badgeFor(title);
  const portrait = variant === 'top10' || variant === 'portrait';
  return (
    <div className={`title-card ${variant}`} ref={ref} onMouseEnter={enter} onMouseLeave={leave}>
      {variant === 'top10' && (
        <svg className="rank" viewBox="0 0 120 150" aria-hidden="true">
          <text x="118" y="140" textAnchor="end">{rank}</text>
        </svg>
      )}
      <button className="card-btn" onClick={() => openTitle(title.id)} aria-label={title.name}>
        <img src={portrait ? title.poster : title.backdrop || title.poster} alt={title.name} loading="lazy" />
        {!portrait && <span className="card-name">{title.name}</span>}
        {title.top10_rank && variant !== 'top10' && (
          <span className="top10-badge" aria-label="Top 10"><small>TOP</small>10</span>
        )}
        {badge && progress == null && <span className="card-badge">{badge}</span>}
        {progress != null && (
          <span className="card-progress"><span style={{ width: `${Math.min(100, progress)}%` }} /></span>
        )}
      </button>
      {rect && <Preview title={title} rect={rect} onClose={() => setRect(null)} onEnter={keepOpen} />}
    </div>
  );
}
