import json, os, hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / 'app/backend/titles.json').read_text())
OUT = Path(__file__).resolve().parent / 'init'
OUT.mkdir(parents=True, exist_ok=True)

def esc(s):
    if s is None: return 'NULL'
    return "'" + str(s).replace("'", "''") + "'"

def norm_asset(p, fallback=None):
    if not p: p = fallback
    if not p: return None
    if p.startswith('assets/'): return '/' + p
    if p.startswith('/assets/'): return p
    return '/assets/' + p.lstrip('/')

def hash_password(password, salt='netflix_seed_salt_2026'):
    iters=120000
    h=hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iters).hex()
    return f'pbkdf2_sha256${iters}${salt}${h}'

langs={'en':'English','ja':'Japanese','zh':'Chinese','ko':'Korean','af':'Afrikaans','es':'Spanish','ru':'Russian','hi':'Hindi','de':'German'}
clips=sorted(os.listdir(ROOT/'app/frontend/public/assets/video'))

# deterministic top-10 by rating across all titles
ranked=sorted([t for t in DATA if t.get('rating',0)>0], key=lambda t: (-t['rating'], t['name']))[:10]
top10={t['id']:i+1 for i,t in enumerate(ranked)}

schema = r'''CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS profiles (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  avatar TEXT NOT NULL,
  is_kids BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS titles (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  year TEXT,
  genre TEXT,
  maturity_rating TEXT,
  rating REAL DEFAULT 0,
  synopsis TEXT,
  poster TEXT,
  backdrop TEXT,
  video_url TEXT,
  duration INTEGER DEFAULT 0,
  top10_rank INTEGER,
  language TEXT,
  language_name TEXT
);
CREATE TABLE IF NOT EXISTS episodes (
  id SERIAL PRIMARY KEY,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  season INTEGER NOT NULL,
  number INTEGER NOT NULL,
  name TEXT NOT NULL,
  synopsis TEXT,
  duration INTEGER DEFAULT 0,
  thumbnail TEXT
);
CREATE TABLE IF NOT EXISTS genres (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS title_genres (
  id SERIAL PRIMARY KEY,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
  UNIQUE(title_id, genre_id)
);
CREATE TABLE IF NOT EXISTS my_list (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE(profile_id, title_id)
);
CREATE TABLE IF NOT EXISTS ratings (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  value INTEGER NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE(profile_id, title_id)
);
CREATE TABLE IF NOT EXISTS continue_watching (
  id SERIAL PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
  progress_seconds INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE(profile_id, title_id)
);
CREATE INDEX IF NOT EXISTS idx_titles_kind ON titles(kind);
CREATE INDEX IF NOT EXISTS idx_episodes_title ON episodes(title_id, season, number);
CREATE INDEX IF NOT EXISTS idx_my_list_profile ON my_list(profile_id);
CREATE INDEX IF NOT EXISTS idx_ratings_profile ON ratings(profile_id);
CREATE INDEX IF NOT EXISTS idx_cw_profile ON continue_watching(profile_id);
'''

rows=[]
rows.append("-- Netflix clone seed data generated from dataset/titles.json")
rows.append("INSERT INTO users (id,email,password_hash,name) VALUES (1,'demo@netflix.com',%s,'Demo Viewer') ON CONFLICT (email) DO NOTHING;" % esc(hash_password('demo123')))
avatars=['/assets/avatars/avatar_1.svg','/assets/avatars/avatar_2.svg','/assets/avatars/avatar_3.svg','/assets/avatars/avatar_4.svg','/assets/avatars/avatar_5.svg','/assets/avatars/avatar_6.svg']
rows.append("INSERT INTO profiles (id,user_id,name,avatar,is_kids) VALUES "
            "(1,1,'Alex',%s,FALSE),(2,1,'Jamie',%s,FALSE),(3,1,'Little Ones',%s,TRUE) ON CONFLICT (id) DO NOTHING;" % tuple(map(esc,avatars[:3])))
# genres
genres=[]
for t in DATA:
    gs=t.get('genres') or ([t.get('genre')] if t.get('genre') else [])
    for g in gs:
        if g and g not in genres: genres.append(g)
for i,g in enumerate(genres,1):
    rows.append(f"INSERT INTO genres (id,name) VALUES ({i},{esc(g)}) ON CONFLICT (name) DO NOTHING;")
gid={g:i for i,g in enumerate(genres,1)}
for t in DATA:
    poster=norm_asset(t.get('poster'))
    backdrop=norm_asset(t.get('backdrop'), t.get('poster'))
    vid='/assets/video/'+clips[(t['id']-1)%len(clips)]
    duration=(2400 + (t['id'] * 97) % 1200) if t['kind']=='series' else (4800 + (t['id'] * 173) % 3000)
    lang=t.get('language') or 'en'
    rows.append("INSERT INTO titles (id,name,kind,year,genre,maturity_rating,rating,synopsis,poster,backdrop,video_url,duration,top10_rank,language,language_name) VALUES (%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%d,%s,%s,%s) ON CONFLICT (id) DO NOTHING;" % (
        t['id'],esc(t['name']),esc(t['kind']),esc(t.get('year')),esc(t.get('genre')),esc(t.get('maturity_rating')),float(t.get('rating') or 0),esc(t.get('synopsis')),esc(poster),esc(backdrop),esc(vid),duration,('NULL' if t['id'] not in top10 else str(top10[t['id']])),esc(lang),esc(langs.get(lang,lang))))
    gs=t.get('genres') or ([t.get('genre')] if t.get('genre') else [])
    for g in gs:
        if g in gid:
            rows.append(f"INSERT INTO title_genres (title_id,genre_id) VALUES ({t['id']},{gid[g]}) ON CONFLICT DO NOTHING;")
# episodes for every series: 2 seasons x 3 episodes
epnum=1
chapter=['First Light','The Invitation','Crossroads','Hidden Depths','After the Storm','The Reckoning','Second Chances','The Long Way Home','No Easy Answers','The Truth','New Ground','Turning Point']
for t in DATA:
    if t['kind']!='series': continue
    backdrop=norm_asset(t.get('backdrop'), t.get('poster'))
    for season in (1,2):
        for number in (1,2,3):
            name=chapter[(t['id'] * 7 + (season - 1) * 3 + number - 1) % len(chapter)]
            synopsis=t.get('synopsis') or ''
            episode_duration=28*60 + ((t['id']*37 + season*13 + number*7) % (22*60))
            rows.append("INSERT INTO episodes (id,title_id,season,number,name,synopsis,duration,thumbnail) VALUES (%d,%d,%d,%d,%s,%s,%d,%s) ON CONFLICT (id) DO NOTHING;" % (epnum,t['id'],season,number,esc(name),esc(synopsis),episode_duration,esc(backdrop)))
            epnum+=1
# seeded per-profile private data for the demo account
for title_id in (22,36,42,15,2):
    rows.append(f"INSERT INTO my_list (profile_id,title_id) VALUES (1,{title_id}) ON CONFLICT DO NOTHING;")
for title_id in (22,36,42):
    rows.append(f"INSERT INTO my_list (profile_id,title_id) VALUES (2,{title_id}) ON CONFLICT DO NOTHING;")
for title_id,progress in ((22,1180),(36,640),(42,1900),(7,240)):
    rows.append(f"INSERT INTO continue_watching (profile_id,title_id,progress_seconds) VALUES (1,{title_id},{progress}) ON CONFLICT (profile_id,title_id) DO UPDATE SET progress_seconds=EXCLUDED.progress_seconds;")
for title_id,val in ((22,2),(36,1),(42,1),(6,-1)):
    rows.append(f"INSERT INTO ratings (profile_id,title_id,value) VALUES (1,{title_id},{val}) ON CONFLICT (profile_id,title_id) DO UPDATE SET value=EXCLUDED.value;")
# keep sequences above explicit seed ids
for table in ('users','profiles','episodes','genres'):
    rows.append(f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE((SELECT MAX(id) FROM {table}),1));")
(OUT/'01_schema.sql').write_text(schema)
(OUT/'02_seed.sql').write_text('\n'.join(rows)+'\n')
print('wrote', OUT/'01_schema.sql', OUT/'02_seed.sql', 'genres',len(genres),'episodes',epnum-1)
