import icons from '../icons';

export default function Icon({ name, size = 24, className = '', style }) {
  const svg = icons[name] || icons[`nf-${name}`];
  return (
    <span
      className={`icon ${className}`}
      style={{ width: size, height: size, ...style }}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
