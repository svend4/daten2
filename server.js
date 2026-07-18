// server.js — «капабилити-роутер».
// Стоит перед 7 уровнями-магазинами, определяет живые через /api/health
// и маршрутизирует запросы по единому контракту на выбранный уровень.
const express = require('express');
const path = require('path');
const { LEVELS, SERVICES } = require('./registry');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const DEFAULT_LEVEL = parseInt(process.env.DEFAULT_LEVEL || '6', 10);
const PROBE_TIMEOUT = parseInt(process.env.PROBE_TIMEOUT || '2000', 10);

// --- health-проба одного уровня ---
async function probe(l) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), PROBE_TIMEOUT);
  try {
    const r = await fetch(l.url + '/api/health', { signal: ac.signal });
    clearTimeout(timer);
    if (!r.ok) return { ...l, up: false };
    return { ...l, up: true, reported: await r.json() };
  } catch {
    clearTimeout(timer);
    return { ...l, up: false };
  }
}

const healthAll = () => Promise.all(LEVELS.map(probe));

// --- выбор целевого уровня по политике ---
async function chooseTarget(reqLevel) {
  const statuses = await healthAll();
  const up = statuses.filter((s) => s.up);
  if (reqLevel) {
    const pinned = up.find((s) => s.level === Number(reqLevel));
    if (pinned) return pinned;
  }
  const def = up.find((s) => s.level === DEFAULT_LEVEL);
  if (def) return def;
  // иначе — самый «способный» из доступных (высший уровень)
  return up.sort((a, b) => b.level - a.level)[0] || null;
}

// --- прокси на выбранный уровень ---
async function forward(res, target, pathname, init) {
  if (!target) return res.status(503).json({ error: 'no level available' });
  try {
    const r = await fetch(target.url + pathname, init);
    const body = await r.text();
    res.status(r.status);
    res.set('X-Served-By-Level', String(target.level));
    res.set('X-Served-By-Stack', target.stack);
    res.set('Content-Type', r.headers.get('content-type') || 'application/json');
    res.send(body);
  } catch {
    res.status(502).json({ error: 'upstream error', level: target.level });
  }
}

// --- служебные эндпоинты роутера ---
app.get('/gateway/health', async (_, res) => res.json(await healthAll()));
app.get('/gateway/config', (_, res) => res.json({ defaultLevel: DEFAULT_LEVEL, levels: LEVELS, services: SERVICES }));

// --- общие сервисы: auth и payment (реализованы один раз, а не на каждом уровне) ---
async function proxyService(req, res, base) {
  try {
    const init = { method: req.method, headers: {} };
    if (req.headers.authorization) init.headers.Authorization = req.headers.authorization;
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(req.body || {});
    }
    const r = await fetch(base + req.originalUrl, init);
    const body = await r.text();
    res.status(r.status);
    res.set('Content-Type', r.headers.get('content-type') || 'application/json');
    res.send(body);
  } catch {
    res.status(502).json({ error: 'service unavailable' });
  }
}

app.all('/api/auth/*', (req, res) => proxyService(req, res, SERVICES.auth));
app.all('/api/payments/*', (req, res) => proxyService(req, res, SERVICES.payment));

// --- проксируемый единый контракт (?level=N для явного пина) ---
app.get('/api/products', async (req, res) => {
  const target = await chooseTarget(req.query.level);
  await forward(res, target, '/api/products');
});

app.post('/api/orders', async (req, res) => {
  const target = await chooseTarget(req.query.level);
  await forward(res, target, '/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req.body || {}),
  });
});

// заказ живёт в БД создавшего уровня — при чтении обязателен ?level=N
app.get('/api/orders/:token', async (req, res) => {
  const target = await chooseTarget(req.query.level);
  await forward(res, target, '/api/orders/' + encodeURIComponent(req.params.token));
});

const PORT = process.env.PORT || 8080;
if (require.main === module) {
  app.listen(PORT, () => console.log(`capability-router on :${PORT} (default level ${DEFAULT_LEVEL})`));
}

module.exports = app;
