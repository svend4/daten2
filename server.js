// server.js — самооптимизирующийся капабилити-роутер.
// Проксирует единый контракт на выбранный «мозгом» уровень, измеряет латентность и
// исход, обучает модель и при сбое делает failover на следующий по полезности уровень.
const express = require('express');
const path = require('path');
const registry = require('./registry');
const brain = require('./brain');
const explain = require('./explain');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

brain.configure(registry.backends);

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advisor = null;
if (HAS_KEY) {
  try { advisor = require('./advisor'); }
  catch (e) { console.error('LLM-советник недоступен, используется детерминированный:', e.message); }
}
const ENGINE_NAME = advisor ? 'llm' : 'rules';
const sessions = new Map();

// --- контрольные эндпоинты роутера ---
app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backends: registry.backends.length }));
app.get('/api/router/stats', (_, res) => res.json({ decision: brain.decide(), levels: brain.snapshot() }));
app.get('/api/router/decide', (_, res) => res.json(brain.decide()));
app.post('/api/router/refresh', async (_, res) => { const r = await brain.refresh(); res.json({ ok: true, backends: r }); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  const message = (req.body && req.body.message) || '';
  let session = sessions.get(sid);
  if (!session) { session = {}; sessions.set(sid, session); }
  try {
    const engine = advisor || explain;
    const out = await engine.ask(session, message);
    res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// --- прокси единого контракта на выбранный уровень (с обучением и failover) ---
async function route(req, res, id, tried) {
  const b = brain.find(id);
  brain.start(id);
  const t = Date.now();
  try {
    const r = await fetch(b.url + req.originalUrl, {
      method: req.method,
      headers: { 'Content-Type': 'application/json' },
      body: ['GET', 'HEAD'].includes(req.method) ? undefined : JSON.stringify(req.body || {}),
      signal: AbortSignal.timeout(Number(process.env.PROXY_TIMEOUT_MS || 5000)),
    });
    const text = await r.text();
    brain.record(id, { latencyMs: Date.now() - t, ok: r.ok });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    res.status(r.status).set('X-Served-By-Level', id).type('application/json').send(text);
  } catch (e) {
    brain.record(id, { latencyMs: Date.now() - t, ok: false });
    tried.add(id);
    const next = brain.decide().scored.find((s) => !tried.has(s.id) && s.alive);
    if (next) return route(req, res, next.id, tried);
    res.status(502).set('X-Served-By-Level', id).json({ error: 'все бэкенды недоступны: ' + e.message });
  }
}

async function proxy(req, res) {
  const { choice } = brain.decide();
  if (!choice) return res.status(503).json({ error: 'нет доступных бэкендов' });
  return route(req, res, choice, new Set());
}

app.all(['/api/products', '/api/products/:id', '/api/orders', '/api/orders/:id'], proxy);

const PORT = process.env.PORT || 8073;
const HEALTH_MS = Number(process.env.HEALTH_MS || 15000);
if (require.main === module) {
  brain.refresh().then((r) => console.log('живые уровни:', r.filter((x) => x.alive).map((x) => x.id).join(', ') || 'нет'));
  setInterval(() => brain.refresh(), HEALTH_MS);
  app.listen(PORT, () => console.log(`ai-router on :${PORT} (движок: ${ENGINE_NAME}, уровней: ${registry.backends.length})`));
}

module.exports = app;
