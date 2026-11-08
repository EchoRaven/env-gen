const ROOT_ICONS = {
  pause: '/assets/icons/pause.svg',
  check: '/assets/icons/check.svg',
  chevron_right: '/assets/icons/chevron-right.svg',
  x: '/assets/icons/x.svg',
}

export function AssetIcon({ name, size = 24, className = '', style }) {
  return (
    <img
      className={`asset-icon ${className}`}
      src={ROOT_ICONS[name] || `/assets/icons/netflix/${name}.svg`}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      style={style}
    />
  )
}

export function Wordmark({ height = 27, className = '' }) {
  return (
    <img
      className={`wordmark ${className}`}
      src="/assets/brand/netflix_wordmark.svg"
      alt="Netflix"
      style={{ height }}
    />
  )
}

export function NIcon({ size = 20, className = '' }) {
  return (
    <img
      className={className}
      src="/assets/brand/netflix_n_icon.svg"
      alt="Netflix"
      width={size}
      height={size}
    />
  )
}

