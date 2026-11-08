import { useCallback, useMemo } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { TitleModal } from '../components/TitleModal'
import BrowsePage from './BrowsePage'

export default function TitleDetailPage() {
  const { titleId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const close = useCallback(() => {
    const from = location.state?.from
    navigate(from || '/browse')
  }, [location.state, navigate])

  const background = useMemo(() => {
    const from = location.state?.from || '/browse'
    let path = from
    let search = ''
    try {
      const parsed = new URL(from, window.location.origin)
      path = parsed.pathname
      search = parsed.search
    } catch {
      // The fallback path above remains usable.
    }
    if (path.startsWith('/shows')) return { mode: 'shows' }
    if (path.startsWith('/movies')) return { mode: 'movies' }
    if (path.startsWith('/new')) return { mode: 'new' }
    if (path.startsWith('/my-list')) return { mode: 'my-list' }
    if (path.startsWith('/games')) return { mode: 'games' }
    if (path.startsWith('/browse/languages')) return { mode: 'languages' }
    if (path.startsWith('/browse/genre/')) return { mode: 'genre', genreOverride: path.split('/').filter(Boolean).pop() }
    if (path.startsWith('/search')) return { mode: 'search', queryOverride: new URLSearchParams(search).get('q') || '' }
    return { mode: 'home' }
  }, [location.state])

  return (
    <>
      <BrowsePage mode={background.mode} genreOverride={background.genreOverride} queryOverride={background.queryOverride} />
      <TitleModal titleId={Number(titleId)} onClose={close} />
    </>
  )
}
