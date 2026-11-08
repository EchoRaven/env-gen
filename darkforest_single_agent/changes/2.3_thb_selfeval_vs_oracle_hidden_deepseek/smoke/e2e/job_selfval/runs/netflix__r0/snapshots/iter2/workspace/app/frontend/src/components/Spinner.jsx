export default function Spinner({ label = 'Loading' }) {
  return (
    <div className="loading-state" role="status">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  )
}
