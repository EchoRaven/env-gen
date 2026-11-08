export default function Icon({ name, size = 24, className = '', title = '' }) {
  return (
    <span
      className={`icon ${className}`}
      role={title ? 'img' : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      style={{
        width: size,
        height: size,
        WebkitMaskImage: `url(/assets/icons/${name}.svg)`,
        maskImage: `url(/assets/icons/${name}.svg)`,
      }}
    />
  )
}

export function BrandLogo({ className = '' }) {
  return <img className={`brand-logo ${className}`} src="/assets/brand/netflix_wordmark.svg" alt="Netflix" />
}
