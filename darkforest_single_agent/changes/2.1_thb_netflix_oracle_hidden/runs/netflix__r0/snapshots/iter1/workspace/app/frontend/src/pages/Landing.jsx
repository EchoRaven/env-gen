import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Icon from '../components/Icon';

// Poster files shipped with the catalog (public/assets/posters) for the collage.
const POSTERS = [
  'tv_66732', 'movie_1368337', 'tv_94997', 'movie_969681', 'tv_125988', 'movie_1003596', 'tv_60625', 'movie_1228710',
  'tv_37854', 'movie_1108427', 'tv_138502', 'movie_1084244', 'tv_124364', 'movie_687163', 'tv_296206', 'movie_1081003',
  'tv_254528', 'movie_1275779', 'tv_2122', 'movie_931285', 'tv_279323', 'movie_1315772', 'tv_255358', 'movie_1314481',
  'tv_94664', 'movie_1212763', 'tv_278624', 'movie_1468683', 'tv_241882', 'movie_1083381', 'tv_277439', 'movie_1273221',
  'tv_298610', 'movie_1339713', 'tv_289139', 'movie_1318621', 'tv_286709', 'movie_1284465', 'tv_2734', 'movie_936075',
];

const COPY = {
  en: {
    title: 'Unlimited movies, TV shows, and more',
    sub: 'Starts at $8.99. Cancel anytime.',
    ready: 'Ready to watch? Enter your email to create or restart your membership.',
    email: 'Email address', cta: 'Get Started', signin: 'Sign In',
    promoT: 'The Netflix you love for just $8.99.', promoS: 'Get our most affordable, ad-supported plan.', learn: 'Learn More',
  },
  es: {
    title: 'Películas y series ilimitadas y mucho más',
    sub: 'A partir de $8.99. Cancela cuando quieras.',
    ready: '¿Quieres ver algo ya? Escribe tu email para crear o reiniciar tu membresía.',
    email: 'Email', cta: 'Comenzar', signin: 'Iniciar sesión',
    promoT: 'El Netflix que te encanta por solo $8.99.', promoS: 'Obtén nuestro plan más económico con anuncios.', learn: 'Más información',
  },
};

export default function Landing() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [lang, setLang] = useState('en');
  const t = COPY[lang];
  const start = (e) => {
    e.preventDefault();
    navigate(`/signup${email ? `?email=${encodeURIComponent(email)}` : ''}`);
  };
  return (
    <div className="landing">
      <div className="landing-collage" aria-hidden="true">
        <div className="collage-grid">
          {[...POSTERS, ...POSTERS].map((p, i) => <img key={i} src={`/assets/posters/${p}.jpg`} alt="" />)}
        </div>
      </div>
      <div className="landing-shade" />
      <header className="landing-header">
        <img className="landing-logo" src="/assets/brand/netflix_wordmark.svg" alt="NETFLIX" />
        <div className="landing-actions">
          <label className="lang-select">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M4 5h8M8 3v2m2 0c-1 5-4 8-7 9m3-5c1 2 3 4 6 5M13 21l4-10 4 10m-6.5-3h5" /></svg>
            <select value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Language">
              <option value="en">English</option>
              <option value="es">Español</option>
            </select>
          </label>
          <Link className="btn-red small" to="/login">{t.signin}</Link>
        </div>
      </header>
      <section className="landing-hero">
        <h1>{t.title}</h1>
        <p className="landing-sub">{t.sub}</p>
        <form className="landing-form" onSubmit={start}>
          <p>{t.ready}</p>
          <div className="landing-row">
            <input type="email" placeholder={t.email} value={email} onChange={(e) => setEmail(e.target.value)} aria-label={t.email} />
            <button className="btn-red big" type="submit">{t.cta} <Icon name="chevron-right" size={28} /></button>
          </div>
        </form>
      </section>
      <div className="landing-curve" />
      <section className="landing-promo">
        <div className="promo-card">
          <svg className="popcorn" viewBox="0 0 92 92" aria-hidden="true">
            <ellipse cx="46" cy="84" rx="30" ry="5" fill="rgba(0,0,0,.4)" />
            <g fill="#fff6dc"><circle cx="28" cy="26" r="10" /><circle cx="44" cy="18" r="12" /><circle cx="61" cy="25" r="10" /><circle cx="36" cy="32" r="9" /><circle cx="54" cy="33" r="9" /></g>
            <path d="M18 34h56l-7 48H25z" fill="#fff" />
            <path d="M25 34h8l3 48h-7zM42 34h8v48h-8zM59 34h8l-4 48h-7z" fill="#e50914" />
            <circle cx="46" cy="58" r="9" fill="#e50914" stroke="#fff" strokeWidth="2.5" />
            <path d="M46 52l2 4.2 4.5.4-3.4 3 1 4.4-4.1-2.4-4.1 2.4 1-4.4-3.4-3 4.5-.4z" fill="#fff" />
          </svg>
          <div>
            <b>{t.promoT}</b>
            <span>{t.promoS}</span>
          </div>
          <Link className="btn-grey" to="/signup">{t.learn}</Link>
        </div>
      </section>
    </div>
  );
}
