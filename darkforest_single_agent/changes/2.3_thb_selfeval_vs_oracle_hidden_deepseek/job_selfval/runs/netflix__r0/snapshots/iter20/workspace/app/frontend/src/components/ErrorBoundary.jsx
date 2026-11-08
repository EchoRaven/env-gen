import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Netflix UI error', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="error-boundary">
        <img src="/assets/brand/netflix_wordmark.svg" alt="Netflix" />
        <h1>Something went wrong</h1>
        <p>The catalog hit an unexpected error. Your profile data is still safe.</p>
        <div>
          <button type="button" className="btn btn-play" onClick={() => window.location.reload()}>Try Again</button>
          <button type="button" className="btn btn-info" onClick={() => { window.location.href = '/' }}>Go to Home</button>
        </div>
      </div>
    )
  }
}
