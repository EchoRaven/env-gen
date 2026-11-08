import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { Billboard } from '../components/Billboard'
import { Footer } from '../components/Footer'
import { Header } from '../components/Header'
import { RateDialog } from '../components/RateDialog'
import { TitleCard } from '../components/TitleCard'
import { TitleRow } from '../components/TitleRow'
import { NIcon } from '../icons'
import { LANGUAGES, languageName } from '../utils'

const PAGE_TITLES = {
  shows: 'TV Shows',
  movies: 'Movies',
  games: 'Games',
  new: 'New & Popular',
  'my-list': 'My List',
}

function uniqueTitles(items) {
  const seen = new Set()
  return items.filter((item) => {
    if (!item || seen.has(item.id)) return false
    seen.add(item.id)
    return true
  })
}

function sortByRating(items) {
  return [...items].sort((a, b) => Number(b.rating) - Number(a.rating))
}

export default function BrowsePage({ mode = 'home', genreOverride = null, queryOverride = null }) {
  const { authFetch } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const params = useParams()
  const genreId = genreOverride || params.genreId
  const [searchParams] = useSearchParams()
  const query = queryOverride ?? searchParams.get('q') ?? ''
  const language = searchParams.get('language') || ''
  const [library, setLibrary] = useState([])
  const [trending, setTrending] = useState([])
  const [topSeries, setTopSeries] = useState([])
  const [topMovies, setTopMovies] = useState([])
  const [genres, setGenres] = useState([])
  const [myList, setMyList] = useState([])
  const [continueWatching, setContinueWatching] = useState([])
  const [genreTitles, setGenreTitles] = useState([])
  const [languageTitles, setLanguageTitles] = useState([])
  const [searchResults, setSearchResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [rateTitle, setRateTitle] = useState(null)
  const [toast, setToast] = useState('')
  const [genreMenuOpen, setGenreMenuOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [allTitles, trend, genreList, listEntries, continueEntries] = await Promise.all([
        authFetch('/api/titles?limit=100'),
        authFetch('/api/titles/trending?limit=20'),
        authFetch('/api/genres'),
        authFetch('/api/my-list'),
        authFetch('/api/continue-watching'),
      ])
      setLibrary(allTitles)
      setTrending(trend)
      setGenres(genreList)
      setMyList(listEntries)
      setContinueWatching(continueEntries)

      if (mode === 'new') {
        const [series, movies] = await Promise.all([
          authFetch('/api/titles/top10?kind=series&limit=10'),
          authFetch('/api/titles/top10?kind=movie&limit=10'),
        ])
        setTopSeries(series)
        setTopMovies(movies)
      }
      if (mode === 'genre' && genreId) {
        setGenreTitles(await authFetch(`/api/genres/${genreId}/titles?limit=100`))
      }
      if (mode === 'languages') {
        setLanguageTitles(language ? await authFetch(`/api/titles?language=${encodeURIComponent(language)}&limit=100`) : allTitles)
      }
      if (mode === 'search') {
        setSearchResults(query ? await authFetch(`/api/search?q=${encodeURIComponent(query)}`) : [])
      }
    } catch (requestError) {
      setError(requestError.message || 'The catalog could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [authFetch, mode, genreId, language, query])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!toast) return undefined
    const timer = window.setTimeout(() => setToast(''), 2600)
    return () => window.clearTimeout(timer)
  }, [toast])

  const openTitle = (title) => {
    navigate(`/title/${title.id}`, { state: { from: location.pathname + location.search } })
  }
  const playTitle = (title) => navigate(`/watch/${title.id}`)

  const updateTitleState = (titleId, inMyList) => {
    const update = (items) => items.map((item) => (item.id === titleId ? { ...item, in_my_list: inMyList } : item))
    setLibrary(update)
    setTrending(update)
    setTopSeries(update)
    setTopMovies(update)
    setGenreTitles(update)
    setLanguageTitles(update)
    setSearchResults(update)
    setMyList((items) =>
      inMyList ? items : items.filter((item) => (item.title_id || item.id) !== titleId),
    )
  }

  const updateRatingState = (titleId, value) => {
    const update = (items) => items.map((item) => (item.id === titleId ? { ...item, my_rating: value } : item))
    setLibrary(update)
    setTrending(update)
    setTopSeries(update)
    setTopMovies(update)
    setGenreTitles(update)
    setLanguageTitles(update)
    setSearchResults(update)
  }

  const toggleList = async (title, currentlyInList) => {
    try {
      if (currentlyInList) {
        await authFetch(`/api/my-list/${title.id}`, { method: 'DELETE' })
        updateTitleState(title.id, false)
        setToast(`Removed ${title.name} from My List`)
      } else {
        const entry = await authFetch('/api/my-list', { method: 'POST', body: { title_id: title.id } })
        updateTitleState(title.id, true)
        setMyList((items) => [{ ...entry, in_my_list: true }, ...items.filter((item) => item.title_id !== title.id)])
        setToast(`Added ${title.name} to My List`)
      }
    } catch (requestError) {
      setToast(requestError.message || 'Could not update My List.')
    }
  }

  const myListTitles = useMemo(
    () => uniqueTitles(myList.map((entry) => ({ ...(entry.title || entry), in_my_list: true, progress_seconds: entry.progress_seconds }))),
    [myList],
  )
  const continueTitles = useMemo(
    () => uniqueTitles(continueWatching.map((entry) => ({ ...(entry.title || entry), in_my_list: entry.in_my_list, progress_seconds: entry.progress_seconds }))),
    [continueWatching],
  )
  const series = useMemo(() => sortByRating(library.filter((item) => item.kind === 'series')), [library])
  const movies = useMemo(() => sortByRating(library.filter((item) => item.kind === 'movie')), [library])
  const newest = useMemo(() => sortByRating(library.filter((item) => String(item.year) >= '2025')), [library])
  const byGenre = useCallback(
    (name, items = library) => items.filter((item) => (item.genres || []).some((genre) => genre.toLowerCase() === name.toLowerCase())),
    [library],
  )

  const currentGenre = genres.find((genre) => String(genre.id) === String(genreId))
  const hero = useMemo(() => {
    if (mode === 'genre') return genreTitles[0] || null
    if (mode === 'languages') return languageTitles[0] || null
    if (mode === 'shows') return series.find((item) => item.id === 28) || series[0] || null
    if (mode === 'movies') return movies.find((item) => item.id === 1) || movies[0] || null
    if (mode === 'new') return newest[0] || trending[0] || null
    if (mode === 'games') return null
    return trending.find((item) => item.id === 22) || trending[0] || library[0] || null
  }, [mode, genreTitles, languageTitles, series, movies, newest, trending, library])

  const showPageHeader = ['shows', 'movies', 'languages', 'genre'].includes(mode)
  const pageTitle = mode === 'genre' ? 'TV Shows' : mode === 'languages' ? 'Browse by Languages' : PAGE_TITLES[mode]
  const heroLabel =
    mode === 'shows' ? 'SERIES' : mode === 'movies' ? 'FILM' : mode === 'genre' ? (currentGenre?.name || 'COLLECTION').toUpperCase() : undefined
  const rankLabel = hero?.top10_rank && (mode === 'shows' || mode === 'movies')
    ? `#${hero.top10_rank} in ${mode === 'shows' ? 'TV Shows' : 'Movies'} Today`
    : null

  const selectGenre = (value) => {
    if (value) navigate(`/browse/genre/${value}`)
  }
  const openRandom = (items) => {
    if (items.length) openTitle(items[Math.floor(Math.random() * items.length)])
  }

  const cardGrid = (items, emptyMessage) =>
    loading ? (
      <div className="poster-grid">
        {Array.from({ length: 12 }).map((_, index) => <div className="skeleton-card grid-skeleton" key={index}><span /></div>)}
      </div>
    ) : items.length ? (
      <div className="poster-grid">
        {items.map((item, index) => (
          <TitleCard
            key={item.id}
            title={item}
            inList={item.in_my_list}
            index={index}
            onOpen={openTitle}
            onPlay={playTitle}
            onToggleList={toggleList}
            onRate={setRateTitle}
          />
        ))}
      </div>
    ) : (
      <div className="grid-empty">
        <p>{emptyMessage}</p>
        <button className="button button-white" onClick={() => navigate('/browse')}>Browse the catalog</button>
      </div>
    )

  return (
    <div className="browse-page">
      <Header searchPage={mode === 'search'} />
      {error ? (
        <div className="page-error">
          <h1>Unable to load this page</h1>
          <p>{error}</p>
          <button className="button button-white" onClick={load}>Try again</button>
        </div>
      ) : (
        <main>
          {showPageHeader ? (
            <div className={`category-page-head ${mode === 'languages' ? 'languages-head' : ''}`}>
              <div>
                <h1>{pageTitle}</h1>
                {mode === 'genre' ? <span className="category-subtitle">{currentGenre?.name || 'Category'}</span> : null}
              </div>
              {mode === 'shows' || mode === 'movies' ? (
                <div className="genre-dropdown-label">
                  <button className="genre-menu-toggle" onClick={() => setGenreMenuOpen((value) => !value)} aria-expanded={genreMenuOpen}>
                    Genres <span className="nav-caret" />
                  </button>
                  {genreMenuOpen ? (
                    <div className="genre-mega-menu">
                      {genres.map((genre) => (
                        <button key={genre.id} onClick={() => { setGenreMenuOpen(false); selectGenre(genre.id) }}>
                          {genre.name}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {mode === 'languages' ? (
                <span className="preferences-heading">Select Your Preferences</span>
              ) : null}
            </div>
          ) : null}

          {mode === 'games' ? (
            <section className="games-hero">
              <div className="games-hero-bg" />
              <div className="games-hero-content">
                <div className="billboard-kicker"><NIcon size={22} /><span>NETFLIX GAMES</span></div>
                <h1>Games</h1>
                <p>The supplied catalog contains films and series only. Game titles will appear here when they are added to the catalog.</p>
                <div className="billboard-actions">
                  <button className="button button-white" onClick={() => navigate('/browse')}>Browse Shows & Movies</button>
                  <button className="button button-gray" onClick={() => navigate('/new')}>See What's New</button>
                </div>
              </div>
            </section>
          ) : mode === 'my-list' || mode === 'search' ? (
            <section className="simple-page">
              <div className="simple-page-head">
                <h1>{mode === 'search' ? (query ? `Search results for “${query}”` : 'Search') : 'My List'}</h1>
                {mode === 'my-list' ? <span>{myListTitles.length} {myListTitles.length === 1 ? 'title' : 'titles'}</span> : null}
                {mode === 'search' ? <span>{searchResults.length} {searchResults.length === 1 ? 'result' : 'results'}</span> : null}
              </div>
              {mode === 'search' && !query ? (
                <div className="grid-empty"><p>Enter a title, genre or keyword in the search bar.</p></div>
              ) : mode === 'search' ? (
                cardGrid(searchResults, 'No titles matched your search.')
              ) : (
                cardGrid(myListTitles, 'Your list is empty. Add titles with the + button on any title.')
              )}
            </section>
          ) : mode === 'new' ? (
            <section className="new-page">
              <div className="rails-container no-hero">
                <TitleRow title="New on Netflix" items={newest.slice(0, 16)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                <TitleRow title="Top 10 TV Shows in the U.S. Today" items={topSeries} loading={loading} numbered onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                <TitleRow title="Top 10 Movies in the U.S. Today" items={topMovies} loading={loading} numbered onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                <TitleRow title="Coming This Week" items={[...movies.filter((item) => String(item.year) === '2026').slice(0, 8), ...series.filter((item) => String(item.year) === '2026').slice(0, 8)]} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
              </div>
            </section>
          ) : mode === 'languages' ? (
            <section className="languages-page-body">
              <div className="language-controls">
                <LanguageSelect label="Original Language" value={language} onChange={(code) => navigate(`/browse/languages${code ? `?language=${code}` : ''}`)} />
                <LanguageSelect label="Dubbing" value={language} onChange={(code) => navigate(`/browse/languages${code ? `?language=${code}` : ''}`)} />
                <LanguageSelect label="Subtitles" value={language} onChange={(code) => navigate(`/browse/languages${code ? `?language=${code}` : ''}`)} />
              </div>
              <p className="language-note">{language ? `Showing titles with original language: ${languageName(language)}.` : 'Showing every title in the catalog.'}</p>
              {cardGrid(languageTitles, 'No titles are available for this language.')}
            </section>
          ) : (
            <>
              <Billboard title={hero} label={heroLabel} onPlay={playTitle} compact={mode !== 'home'} rankLabel={rankLabel} />
              <div className={`rails-container ${mode !== 'home' ? 'compact-hero' : ''}`}>
                {mode === 'home' ? (
                  <>
                    <TitleRow title="Trending Now" items={trending} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Continue Watching" items={continueTitles} loading={loading} progressRows onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} emptyMessage="Start watching a title and it will appear here." />
                    <TitleRow title="TV Action & Adventure" items={byGenre('Action & Adventure', series)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Games" items={[]} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} emptyMessage="No games are included in the supplied catalog." />
                    <TitleRow title="Only on Netflix" items={trending.slice(0, 16)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    {myListTitles.length ? <TitleRow title="My List" items={myListTitles.slice(0, 16)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} /> : null}
                    <TitleRow title="Top Searches" items={sortByRating(library).slice(0, 16)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="New on Netflix" items={newest.slice(0, 16)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                  </>
                ) : null}
                {mode === 'shows' ? (
                  <>
                    <TitleRow title="Today's Top Picks for You" items={series.slice(0, 16)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="New TV Shows" items={series.filter((item) => String(item.year) >= '2025')} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="TV Dramas" items={byGenre('Drama', series)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="TV Action & Adventure" items={byGenre('Action & Adventure', series)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Sci-Fi & Fantasy TV" items={byGenre('Sci-Fi & Fantasy', series)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Anime" items={byGenre('Animation', series)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                  </>
                ) : null}
                {mode === 'movies' ? (
                  <>
                    <TitleRow title="Gems for You" items={movies.slice(0, 16)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Action Movies" items={byGenre('Action', movies)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Comedies" items={byGenre('Comedy', movies)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Horror Movies" items={byGenre('Horror', movies)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Sci-Fi & Fantasy" items={uniqueTitles([...byGenre('Science Fiction', movies), ...byGenre('Fantasy', movies)])} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                    <TitleRow title="Family Movies" items={byGenre('Family', movies)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                  </>
                ) : null}
                {mode === 'genre' ? (
                  <>
                    <TitleRow title={`All ${currentGenre?.name || 'Titles'}`} items={genreTitles} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} emptyMessage="No titles are assigned to this genre." />
                    <TitleRow title="Popular in This Genre" items={sortByRating(genreTitles).slice(0, 16)} loading={loading} onOpen={openTitle} onPlay={playTitle} onToggleList={toggleList} onRate={setRateTitle} />
                  </>
                ) : null}
              </div>
            </>
          )}
          {!['my-list', 'search'].includes(mode) ? (
            <div className="random-pick-row">
              <button className="random-pick-button" onClick={() => openRandom(library)}>Surprise me</button>
            </div>
          ) : null}
          <Footer />
        </main>
      )}
      {toast ? <div className="toast" role="status">{toast}</div> : null}
      {rateTitle ? (
        <RateDialog
          title={rateTitle}
          currentValue={rateTitle.my_rating}
          onClose={() => setRateTitle(null)}
          onRated={(value) => {
            updateRatingState(rateTitle.id, value)
            setToast('Rating saved to this profile')
          }}
        />
      ) : null}
    </div>
  )
}

function LanguageSelect({ label, value, onChange }) {
  return (
    <label className="language-select-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select a language</option>
        {LANGUAGES.map((language) => <option key={language.code} value={language.code}>{language.name}</option>)}
      </select>
    </label>
  )
}
