import { Navigate, useParams } from 'react-router-dom'

// Deep link /title/:id → open the detail modal over the home page.
export default function TitlePage() {
  const { titleId } = useParams()
  return <Navigate to={`/browse?title=${encodeURIComponent(titleId)}`} replace />
}
