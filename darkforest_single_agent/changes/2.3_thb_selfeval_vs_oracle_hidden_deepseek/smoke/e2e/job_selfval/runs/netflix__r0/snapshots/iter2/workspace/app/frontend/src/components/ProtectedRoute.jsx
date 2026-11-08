import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Spinner from './Spinner'

export default function ProtectedRoute({ children, requireProfile = true }) {
  const { token, profile, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="full-loading"><Spinner label="Loading Netflix…" /></div>
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (requireProfile && !profile) return <Navigate to="/profiles" replace />
  return children
}
