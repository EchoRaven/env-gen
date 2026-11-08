import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import Hero from '../components/Hero'
import Row from '../components/Row'
import { LoadingPage, ErrorState } from '../components/PageUtilities'
import { useOpenTitle } from '../hooks'

export default function GenreCategory() {
  const { genreId } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)
  const openTitle = useOpenTitle()

  useEffect(() => {
    setLoading(true)
    Promise.all([api('/api/genres'), api(`/api/genres/${genreId}/titles`)])
      .then(([genres, titles]) => {
        const genre = genres.find(item => Number(item.id) === Number(genreId))
        setData({ genre, titles, genres })
      }).catch(err => setError(err.message)).finally(() => setLoading(false))
  }, [genreId, nonce])

  if (loading) return <LoadingPage label="Loading category…" />
  if (error) return <ErrorState message={error} onRetry={() => setNonce(v => v + 1)} />
  const titles = data?.titles || []
  if (!data?.genre) return <ErrorState message="This genre does not exist." />
  const series = titles.filter(item => item.kind === 'series')
  const movies = titles.filter(item => item.kind === 'movie')
  const sorted = [...titles].sort((a, b) => b.rating - a.rating)

  return (
    <div className="browse-page genre-page">
      <div className="category-title"><span>{titles.some(item => item.kind === 'series') ? 'TV Shows' : 'Movies'}</span><h1>{data.genre.name}</h1></div>
      <Hero title={sorted[0]} eyebrow={data.genre.name} />
      <div className="rows-container raised">
        <Row title={`Top Picks in ${data.genre.name}`} titles={sorted} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title={`${data.genre.name} TV Shows`} titles={series} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title={`${data.genre.name} Movies`} titles={movies} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
        <Row title={`New in ${data.genre.name}`} titles={titles.filter(item => item.year >= 2026)} onOpen={openTitle} onChanged={() => setNonce(v => v + 1)} />
      </div>
    </div>
  )
}
