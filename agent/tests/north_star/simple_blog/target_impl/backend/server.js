// simple_blog target_impl — Express + better-sqlite3 + JWT Bearer auth.
// All routes under /api. Login returns {token, id, email} in body.
const express = require('express');
const Database = require('better-sqlite3');
const jwt = require('jsonwebtoken');
const crypto = require('crypto');

const JWT_SECRET = 'spike-secret-do-not-reuse';
const PORT = 3000;

const db = new Database(':memory:');
db.pragma('journal_mode = WAL');
db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    author_email TEXT NOT NULL
  );
`);

function hashPassword(password) {
  // Deterministic salted hash; sufficient for the spike (not production).
  return crypto.createHash('sha256').update('spike-salt:' + password).digest('hex');
}

function verifyPassword(password, hash) {
  return hashPassword(password) === hash;
}

function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim().length > 0;
}

function authMiddleware(req, res, next) {
  const header = req.headers['authorization'] || req.headers['Authorization'];
  if (!header || typeof header !== 'string' || !header.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'missing or invalid Authorization header' });
  }
  const token = header.slice('Bearer '.length).trim();
  try {
    const payload = jwt.verify(token, JWT_SECRET);
    if (!payload || !payload.email) {
      return res.status(401).json({ error: 'invalid token payload' });
    }
    const user = db.prepare('SELECT id, email FROM users WHERE email = ?').get(payload.email);
    if (!user) {
      return res.status(401).json({ error: 'user not found' });
    }
    req.user = user;
    next();
  } catch (err) {
    return res.status(401).json({ error: 'invalid or expired token' });
  }
}

const app = express();
app.use(express.json());

app.get('/api/health', (req, res) => {
  res.status(200).json({ status: 'ok' });
});

app.post('/api/register', (req, res) => {
  const { email, password } = req.body || {};
  if (!isNonEmptyString(email) || !isNonEmptyString(password)) {
    return res.status(422).json({ error: 'email and password are required' });
  }
  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
  if (existing) {
    return res.status(400).json({ error: 'email already registered' });
  }
  const info = db
    .prepare('INSERT INTO users (email, password_hash) VALUES (?, ?)')
    .run(email, hashPassword(password));
  return res.status(201).json({ id: info.lastInsertRowid, email });
});

app.post('/api/login', (req, res) => {
  const { email, password } = req.body || {};
  if (!isNonEmptyString(email) || !isNonEmptyString(password)) {
    return res.status(401).json({ error: 'invalid credentials' });
  }
  const user = db.prepare('SELECT id, email, password_hash FROM users WHERE email = ?').get(email);
  if (!user || !verifyPassword(password, user.password_hash)) {
    return res.status(401).json({ error: 'invalid credentials' });
  }
  const token = jwt.sign({ email: user.email, sub: user.id }, JWT_SECRET, { expiresIn: '24h' });
  return res.status(200).json({ token, id: user.id, email: user.email });
});

app.post('/api/posts', authMiddleware, (req, res) => {
  const { title, body } = req.body || {};
  if (!isNonEmptyString(title) || !isNonEmptyString(body)) {
    return res.status(422).json({ error: 'title and body are required' });
  }
  const info = db
    .prepare('INSERT INTO posts (title, body, author_email) VALUES (?, ?, ?)')
    .run(title, body, req.user.email);
  return res.status(201).json({
    id: info.lastInsertRowid,
    title,
    body,
    author_email: req.user.email,
  });
});

app.get('/api/posts/:id', (req, res) => {
  const id = Number.parseInt(req.params.id, 10);
  if (!Number.isFinite(id)) {
    return res.status(404).json({ error: 'post not found' });
  }
  const post = db
    .prepare('SELECT id, title, body, author_email FROM posts WHERE id = ?')
    .get(id);
  if (!post) {
    return res.status(404).json({ error: 'post not found' });
  }
  return res.status(200).json(post);
});

app.get('/api/posts', (req, res) => {
  const rows = db
    .prepare('SELECT id, title, body, author_email FROM posts ORDER BY id ASC')
    .all();
  return res.status(200).json({ items: rows });
});

app.use((err, req, res, next) => {
  if (err && err.type === 'entity.parse.failed') {
    return res.status(400).json({ error: 'invalid JSON body' });
  }
  return res.status(500).json({ error: 'internal server error' });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`simple_blog target listening on :${PORT}`);
});
