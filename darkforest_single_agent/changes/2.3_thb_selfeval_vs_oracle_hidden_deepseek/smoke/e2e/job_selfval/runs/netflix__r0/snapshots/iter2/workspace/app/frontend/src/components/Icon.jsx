const ICONS = {
  play: 'play',
  pause: 'pause',
  plus: 'plus',
  check: 'check',
  search: 'search',
  bell: 'bell',
  close: 'close',
  chevronLeft: 'arrow_left',
  chevronRight: 'chevron-right',
  chevronDown: 'chevron-down',
  volume: 'volume_high',
  volumeOff: 'volume_off',
  thumbUp: 'thumbs_up',
  thumbDown: 'thumbs_down',
  love: 'thumbs_up_two',
  info: 'info',
  subtitles: 'subtitles',
  audio: 'audio_description',
  fullscreen: 'maximize',
  refresh: 'refresh',
  download: 'download',
}

export default function Icon({ name, size = 24, className = '', title }) {
  const file = ICONS[name] || name
  const source = `/assets/icons/netflix/${file}.svg`
  return (
    <span
      role={title ? 'img' : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : 'true'}
      className={`icon ${className}`}
      style={{
        width: size,
        height: size,
        WebkitMaskImage: `url(${source})`,
        maskImage: `url(${source})`,
      }}
    />
  )
}
