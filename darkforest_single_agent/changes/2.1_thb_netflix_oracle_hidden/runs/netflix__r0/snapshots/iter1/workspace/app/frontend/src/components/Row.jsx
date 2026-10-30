import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import TitleCard from './TitleCard';
import Icon from './Icon';

// A horizontally scrolling rail with page indicator + arrows.
export default function Row({ title, titles, variant = 'landscape', link, emptyText, progressFor, badge, testId }) {
  const scroller = useRef(null);
  const [page, setPage] = useState(0);
  const [pages, setPages] = useState(1);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return undefined;
    const update = () => {
      setPages(Math.max(1, Math.ceil(el.scrollWidth / el.clientWidth - 0.05)));
      setPage(Math.round(el.scrollLeft / el.clientWidth));
    };
    update();
    el.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    return () => { el.removeEventListener('scroll', update); window.removeEventListener('resize', update); };
  }, [titles]);

  const scrollBy = (dir) => {
    const el = scroller.current;
    el.scrollBy({ left: dir * (el.clientWidth - 40), behavior: 'smooth' });
  };

  if (titles === null || titles === undefined) {
    return (
      <section className="row loading">
        <h2 className="row-title">{title}</h2>
        <div className={`row-skeleton ${variant}`}>{Array.from({ length: 6 }).map((_, i) => <div key={i} />)}</div>
      </section>
    );
  }
  if (titles.length === 0 && !emptyText) return null;

  return (
    <section className={`row ${variant}`} data-testid={testId}>
      <div className="row-head">
        <h2 className="row-title">
          {link ? <Link to={link}>{title} <span className="explore">Explore All ›</span></Link> : title}
          {badge && <span className="row-badge">{badge}</span>}
        </h2>
        {pages > 1 && (
          <div className="row-pages" aria-hidden="true">
            {Array.from({ length: pages }).map((_, i) => <span key={i} className={i === page ? 'on' : ''} />)}
          </div>
        )}
      </div>
      {titles.length === 0 ? (
        <p className="row-empty">{emptyText}</p>
      ) : (
        <div className="row-wrap">
          {page > 0 && (
            <button className="row-arrow left" aria-label={`Scroll ${title} left`} onClick={() => scrollBy(-1)}>
              <Icon name="chevron-left" size={36} />
            </button>
          )}
          <div className="row-scroller" ref={scroller}>
            {titles.map((t, i) => (
              <TitleCard key={`${t.id}-${i}`} title={t} variant={variant} rank={i + 1} progress={progressFor ? progressFor(t) : undefined} />
            ))}
          </div>
          {page < pages - 1 && (
            <button className="row-arrow right" aria-label={`Scroll ${title} right`} onClick={() => scrollBy(1)}>
              <Icon name="chevron-right" size={36} />
            </button>
          )}
        </div>
      )}
    </section>
  );
}
