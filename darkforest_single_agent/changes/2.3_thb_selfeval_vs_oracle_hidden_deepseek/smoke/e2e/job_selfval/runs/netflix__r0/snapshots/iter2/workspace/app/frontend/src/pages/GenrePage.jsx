import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../api'
import Hero from '../components/Hero'
import Icon from '../components/Icon'
import Spinner from '../components/Spinner'
import TitleModal from '../components/TitleModal'
import TitleRail from '../components/TitleRail'

export default function GenrePage() {
  const { genreId } = useParams()
  const [genre, setGenre] = useState(null)
  const [items, setItems] = useState([])
  const [genres, setGenres] = useState([])
  const [loading, setLoading] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)
  const [selectedTitle, setSelectedTitle] = useState(null)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [data, genreData] = await Promise.all([
        api.get(`/api/genres/${genreId}/titles`),
        api.get('/api/genres'),
      ])
      setItems(data.items || [])
      setGenre(data.genre || null)
      setGenres(genreData.items || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [genreId]) // eslint-disable-line react-hooks/exhaustive-deps
  const heroTitle = useMemo(() => items[0] || null, [items])

  if (loading) return <div className="page-loading"><Spinner label="Loading category…" /></div>
  if (error) return <div className="page-loading"><p>{error}</p><Link className="btn btn-light" to="/browse">Back to browse</Link></div>

  return (
    <div className="genre-page">
      <div className="category-toolbar category-toolbar-top">
        <div>
          <div className="breadcrumb"><Link to="/shows">TV Shows</Link><span>/</span><strong>{genre?.name || 'Category'}</strong></div>
          <h1>{genre?.name || 'Category'}</h1>
        </div>
        <div className="genres-menu-wrap">
          <button className="genres-trigger" onClick={() => setMenuOpen((open) => !open)} aria-expanded={menuOpen}>All Genres <Icon name="chevronDown" size={15} /></button>
          {menuOpen ? (
            <div className="genres-menu">
              <Link to="/browse" onClick={() => setMenuOpen(false)}>Home</Link>
              {genres.map((row) => <Link key={row.id} to={`/browse/genre/${row.id}`} onClick={() => setMenuOpen(false)}>{row.name}</Link>)}
            </div>
          ) : null}
        </div>
      </div>
      <Hero title={heroTitle} badge={genre ? genre.name.toUpperCase() : 'CATEGORY'} onMoreInfo={setSelectedTitle} className="compact" />
      <div className="page-content section-content">
        <TitleRail title={`Popular in ${genre?.name || 'this genre'}`} items={items} onOpen={setSelectedTitle} onChanged={load} />
        <TitleRail title="Because You Watched" items={[...items].reverse()} onOpen={setSelectedTitle} onChanged={load} />
        <TitleRail title="Critically Acclaimed" items={[...items].sort((a, b) => b.rating - a.rating)} onOpen={setSelectedTitle} onChanged={load} />
        {items.length === 0 ? <p className="rail-empty">No titles are available in this genre.</p> : null}
      </div>
      {selectedTitle ? <TitleModal titleId={selectedTitle.id} initialTitle={selectedTitle} onClose={() => setSelectedTitle(null)} onChanged={load} /> : null}
    </div>
  )
}
