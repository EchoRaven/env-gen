import { Link } from 'react-router-dom'

export default function EmptyState({ title, message, actionLabel, actionTo, onAction }) {
  return (
    <div className="empty-state">
      <span className="empty-mark" aria-hidden="true">N</span>
      <h2>{title}</h2>
      {message ? <p>{message}</p> : null}
      {actionLabel && actionTo ? <Link className="btn btn-light" to={actionTo}>{actionLabel}</Link> : null}
      {actionLabel && onAction ? <button className="btn btn-light" onClick={onAction}>{actionLabel}</button> : null}
    </div>
  )
}
