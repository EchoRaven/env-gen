import React from 'react'

const iconNames = {
  play: 'play', pause: 'pause', plus: 'plus', check: 'check', info: 'info',
  search: 'search', bell: 'bell', close: 'close', x: 'close',
  'chevron-down': 'chevron-down', 'chevron-left': 'chevron-left', 'chevron-right': 'chevron-right',
  'thumbs-up': 'thumbs_up', 'thumbs-down': 'thumbs_down',
  'thumbs-up-two': 'thumbs_up_two', volume: 'volume_high', mute: 'volume_off',
  fullscreen: 'maximize', back: 'arrow_left', subtitles: 'subtitles',
  audio: 'audio_description', refresh: 'refresh', flag: 'flag', 'new-episode': 'new_episode',
}

export default function Icon({ name, size = 22, className = '', style }) {
  const file = iconNames[name] || name
  const base = ['thumbs_up', 'thumbs_down', 'thumbs_up_two', 'volume_high', 'volume_off',
    'maximize', 'arrow_left', 'subtitles', 'audio_description', 'refresh', 'flag',
    'new_episode', 'close', 'play', 'plus', 'bell', 'search'].includes(file)
    ? `/assets/icons/netflix/${file}.svg`
    : `/assets/icons/${file}.svg`
  return (
    <span
      className={`icon ${className}`}
      aria-hidden="true"
      style={{
        width: size, height: size, display: 'inline-block', flex: `0 0 ${size}px`,
        backgroundColor: 'currentColor',
        WebkitMaskImage: `url("${base}")`, maskImage: `url("${base}")`,
        WebkitMaskRepeat: 'no-repeat', maskRepeat: 'no-repeat',
        WebkitMaskPosition: 'center', maskPosition: 'center',
        WebkitMaskSize: 'contain', maskSize: 'contain', ...style,
      }}
    />
  )
}
