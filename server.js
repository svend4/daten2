// server.js — green/FinOps-роутер: проксирует контракт на уровень, выбранный по
// многокритериальной композитной стоимости (латентность/деньги/углерод/надёжность),
// учитывает €/энергию/CO2 на каждый запрос.
const express = require('express');
const path = require('path');
const registry = require('./registry');
const model = require('./model');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

model.configure(registry.backends);
const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advisor = null;
if (HAS_KEY) { try { advisor = require('./advisor'); } catch (e) { console.error('LLM-советник недоступен:', e.message); } }
const ENGINE_NAME = advisor ? 'llm' : 'rules';
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backends: registry.backends.length, weights: model.getWeights() }));
app.get('/api/router/stats', (_, res) => res.json({ decision: model.decide(), finops: model.finops() }));
app.get('/api/router/decide', (_, res) => res.json(model.decide()));
app.get('/api/router/finops', (_, res) => res.json(model.finops()));
app.post('/api/router/refresh', async (_, res) => res.json({ ok: true, backends: await model.refresh() }));

// веса критериев (профили: fast/cheap/green)
app.get('/api/weights', (_, res) => res.json(model.getWeights()));
app.post('/api/weights', (req, res) => res.json(model.setWeights(req.body || {})));

async function route(req, res, id, tried) {
  const b = model.find(id); const t = Date.now();
  try {
    const r = await fetch(b.url + req.originalUrl, { method: req.method, headers: { 'Content-Type': 'application/json' }, body: ['GET', 'HEAD'].includes(req.method) ? undefined : JSON.stringify(req.body || {}), signal: AbortSignal.timeout(Number(process.env.PROXY_TIMEOUT_MS || 5000)) });
    const text = await r.text(); const lat = Date.now() - t;
    model.recordServed(id, lat, r.ok);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    res.status(r.status).set('X-Served-By-Level', id).set('X-CO2-mg', String(model.co2mg(b, lat).toFixed(3))).type('application/json').send(text);
  } catch (e) {
    model.recordServed(id, Date.now() - t, false); tried.add(id);
    const next = model.decide().scored.find((s) => !tried.has(s.id) && s.alive);
    if (next) return route(req, res, next.id, tried);
    res.status(502).json({ error: 'все уровни недоступны: ' + e.message });
  }
}
async function proxy(req, res) {
  const { choice } = model.decide();
  if (!choice) return res.status(503).json({ error: 'нет уровней' });
  return route(req, res, choice, new Set());
}
app.all(['/api/products', '/api/products/:id', '/api/orders', '/api/orders/:id'], proxy);

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const eng = advisor || interpret; const out = await eng.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8091;
const HEALTH_MS = Number(process.env.HEALTH_MS || 15000);
if (require.main === module) {
  model.refresh().then((r) => console.log('живые уровни:', r.filter((x) => x.alive).map((x) => x.id).join(', ') || 'нет'));
  setInterval(() => model.refresh(), HEALTH_MS);
  app.listen(PORT, () => console.log(`green-router on :${PORT} (движок: ${ENGINE_NAME}, уровней: ${registry.backends.length})`));
}
module.exports = app;
