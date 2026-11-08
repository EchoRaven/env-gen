import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api'
import Hero from './Hero'
import Icon from './Icon'
import Spinner from './Spinner'
import TitleModal from './TitleModal'
import TitleRail from './TitleRail'

const PAGE_COPY = {
  series: {
    eyebrow: 'TV Shows',
    title: 'TV Shows',
    heroLabel: 'N SERIES',
    primaryRail: "Today's Top Picks for You",
    genreNames: ['Action & Adventure', 'Drama', 'Comedy', 'Sci-Fi & Fantasy'],
  },
  movie: {
    eyebrow: 'Movies',
    title: 'Movies',
    heroLabel: 'N FILM',
    primaryRail: 'Gems for You',
    genreNames: ['Drama', 'Comedy', 'Action', 'Science Fiction'],
  },
}

export default function SectionPage({ kind }) {
  const copy = PAGE_COPY[kind]
  const [titles, setTitles] = useState([])
  const [genres, setGenres] = useState([])
  const [genreRows, setGenreRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [genreMenuOpen, setGenreMenuOpen] = useState(false)
  const [selectedTitle, setSelectedTitle] = useState(null)
  const navigate = useNavigate()

  const load = async () => {
    try {
      const [titleData, genreData] = await Promise.all([
        api.get(`/api/titles?kind=${kind}&sort=rating`),
        api.get('/api/genres'),
      ])
      setTitles(titleData.items || [])
      const allGenres = genreData.items || []
      setGenres(allGenres)
      const wanted = copy.genreNames.map((name) => allGenres.find((genre) => genre.name === name)).filter(Boolean)
      const rows = await Promise.all(wanted.map(async (genre) => {
        const data = await api.get(`/api/genres/${genre.id}/titles`)
        return { genre, items: (data.items || []).filter((title) => title.kind === kind) }
      }))
      setGenreRows(rows.filter((row) => row.items.length))
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [kind])
  useEffect(() => {
    const onDown = (event) => {
      if (!event.target.closest('.genres-menu-wrap')) setGenreMenuOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [])

  const heroTitle = useMemo(() => {
    if (kind === 'series') return titles.find((title) => title.name === 'The Hawk') || titles[0] || null
    return titles[0] || null
  }, [titles, kind])
  const openTitle = (title) => setSelectedTitle(title)
  const openById = (id) => {
    const title = titles.find((row) => row.id === id)
    setSelectedTitle(title || { id })
  }

  if (loading) return <div className="page-loading"><Spinner label={`Loading ${copy.title.toLowerCase()}…`} /></div>

  return (
    <div className="section-page">
      <div className="category-toolbar category-toolbar-top">
        <div>
          <span className="page-kicker">BROWSE</span>
          <h1>{copy.title}</h1>
        </div>
        <div className="genres-menu-wrap">
          <button className="genres-trigger" onClick={() => setGenreMenuOpen((open) => !open)} aria-expanded={genreMenuOpen}>
            Genres <Icon name="chevronDown" size={15} />
          </button>
          {genreMenuOpen ? (
            <div className="genres-menu">
              <Link to={`/browse/genre/${genres[0]?.id || 1}`} onClick={() => setGenreMenuOpen(false)}>All {copy.title}</Link>
              {genres.map((genre) => (
                <Link key={genre.id} to={`/browse/genre/${genre.id}`} onClick={() => setGenreMenuOpen(false)}>
                  {genre.name}
                </Link>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <Hero title={heroTitle} badge={copy.heroLabel} onMoreInfo={openTitle} className="compact" />
      <div className="page-content section-content">
        <TitleRail title={copy.primaryRail} items={titles.slice(0, 18)} onOpen={openTitle} onChanged={load} />
        {genreRows.map((row) => (
          <TitleRail
            key={row.genre.id}
            title={row.genre.name}
            items={row.items.slice(0, 18)}
            onOpen={openTitle}
            onChanged={load}
          />
        ))}
        <div className="explore-callout">
          <div>
            <span className="callout-eyebrow">EXPLORE BEYOND {copy.eyebrow.toUpperCase()}</span>
            <h3>There’s even more to watch.</h3>
            <p>Browse every genre, language, and new arrival in the catalog.</p>
          </div>
          <button className="btn btn-light" onClick={() => navigate('/browse/languages')}>Browse by Languages</button>
        </div>
      </div>
      {selectedTitle ? (
        <TitleModal titleId={selectedTitle.id} initialTitle={selectedTitle.id ? selectedTitle : null} onClose={() => setSelectedTitle(null)} onChanged={load} />
      ) : null}
    </div>
  )
}
