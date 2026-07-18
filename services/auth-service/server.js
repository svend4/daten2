// auth-service — общий сервис авторизации за роутером.
// Реализован один раз для всей системы; уровни/фронтенды делегируют сюда.
// Хранилище — in-memory (демо). В проде здесь Postgres/Redis.
const express = require('express');
const crypto = require('crypto');

const app = express();
app.use(express.json());

const SECRET = process.env.AUTH_SECRET || 'insecure-dev-secret-change-me';

// email -> { id, email, passwordHash, name }
const users = new Map();
let nextId = 1;

// --- хэш пароля (scrypt) ---
function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(password, salt, 64).toString('hex');
  return `${salt}:${hash}`;
}
function verifyPassword(password, stored) {
  const [salt, hash] = stored.split(':');
  const test = crypto.scryptSync(password, salt, 64).toString('hex');
  return crypto.timingSafeEqual(Buffer.from(hash, 'hex'), Buffer.from(test, 'hex'));
}

// --- подписанный токен (HMAC), payload = {uid, exp} ---
function sign(data) { return crypto.createHmac('sha256', SECRET).update(data).digest('base64url'); }
function makeToken(uid) {
  const payload = Buffer.from(JSON.stringify({ uid, exp: Date.now() + 7 * 24 * 3600 * 1000 })).toString('base64url');
  return `${payload}.${sign(payload)}`;
}
function readToken(token) {
  if (!token || !token.includes('.')) return null;
  const [payload, sig] = token.split('.');
  if (sign(payload) !== sig) return null;
  try {
    const data = JSON.parse(Buffer.from(payload, 'base64url').toString());
    return data.exp < Date.now() ? null : data;
  } catch { return null; }
}
function userById(id) {
  for (const u of users.values()) if (u.id === id) return u;
  return null;
}
function currentUser(req) {
  const auth = req.headers.authorization || '';
  if (!auth.startsWith('Bearer ')) return null;
  const data = readToken(auth.slice(7));
  return data ? userById(data.uid) : null;
}

// --- маршруты ---
app.get('/health', (_, res) => res.json({ ok: true, service: 'auth' }));

app.post('/api/auth/register', (req, res) => {
  const email = (req.body?.email || '').trim().toLowerCase();
  const password = req.body?.password || '';
  const name = (req.body?.name || '').trim();
  if (!email || password.length < 6) {
    return res.status(400).json({ error: 'email и пароль (мин. 6 символов) обязательны' });
  }
  if (users.has(email)) return res.status(409).json({ error: 'email уже зарегистрирован' });
  const user = { id: nextId++, email, passwordHash: hashPassword(password), name };
  users.set(email, user);
  res.status(201).json({ token: makeToken(user.id), user: { email, name } });
});

app.post('/api/auth/login', (req, res) => {
  const email = (req.body?.email || '').trim().toLowerCase();
  const password = req.body?.password || '';
  const user = users.get(email);
  if (!user || !verifyPassword(password, user.passwordHash)) {
    return res.status(401).json({ error: 'неверные email или пароль' });
  }
  res.json({ token: makeToken(user.id), user: { email: user.email, name: user.name } });
});

app.get('/api/auth/me', (req, res) => {
  const user = currentUser(req);
  if (!user) return res.status(401).json({ error: 'unauthorized' });
  res.json({ email: user.email, name: user.name });
});

// для других сервисов: валидация токена
app.get('/api/auth/verify', (req, res) => {
  const user = currentUser(req);
  res.json({ valid: !!user, user: user ? { id: user.id, email: user.email } : null });
});

const PORT = process.env.PORT || 8091;
if (require.main === module) {
  app.listen(PORT, () => console.log(`auth-service on :${PORT}`));
}
module.exports = app;
