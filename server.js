// server.js — shadow/canary через роутер.
// primary обслуживает клиента; в shadow-режиме копия запроса зеркалится на
// candidate и ответы диффаются (клиент этого не видит). В canary-режиме доля
// живого трафика идёт на candidate с авто-откатом при росте ошибок.
const express = require('express');
const path = require('path');
const config = require('./config');
const differ = require('./differ');
const stats = require('./stats');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm' : 'rules';
const sessions = new Map();
let canaryAcc = 0;

async function forward(base, req) {
  const t = Date.now();
  try {
    const r = await fetch(base + req.originalUrl, { method: req.method, headers: { 'Content-Type': 'application/json' }, body: ['GET', 'HEAD'].includes(req.method) ? undefined : JSON.stringify(req.body || {}), signal: AbortSignal.timeout(Number(process.env.PROXY_TIMEOUT_MS || 5000)) });
    const text = await r.text(); let body; try { body = text ? JSON.parse(text) : null; } catch { body = text; }
    return { status: r.status, ok: r.ok, body, ms: Date.now() - t };
  } catch (e) { return { status: 502, ok: false, body: { error: e.message }, ms: Date.now() - t, error: e.message }; }
}
const respond = (res, r, side) => res.status(r.status).set('X-Served-By', side).json(r.body);

async function handle(req, res) {
  if (config.mode === 'canary' && config.candidate) return canary(req, res);
  // shadow (или off): клиента всегда обслуживает primary
  const p = await forward(config.primary, req);
  if (config.mode === 'shadow' && config.candidate) {
    const c = await forward(config.candidate, req);
    if (c.error || !c.ok) stats.recordShadow('candidate-error');
    else {
      const cmp = differ.compare(p.body, c.body, config.ignoreFields);
      if (cmp.match) stats.recordShadow('match');
      else stats.recordShadow('diff', { path: req.originalUrl, diffs: cmp.diffs });
    }
  }
  respond(res, p, 'primary');
}

async function canary(req, res) {
  canaryAcc += config.canaryPct;
  let side = 'primary';
  if (canaryAcc >= 1) { canaryAcc -= 1; side = 'candidate'; }
  const base = side === 'candidate' ? config.candidate : config.primary;
  const r = await forward(base, req);
  stats.recordCanary(side, r.ok);
  // авто-откат при росте ошибок кандидата
  const cn = stats.canaryReport();
  if (cn.candidate.served >= config.minSamples && cn.candidate.errorRate > config.rollbackErrorRate) {
    config.canaryPct = 0; config.mode = 'shadow';
    stats.rollback(`ошибки кандидата ${Math.round(cn.candidate.errorRate * 100)}% > порога`);
  }
  respond(res, r, side);
}

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, mode: config.mode, primary: config.primary, candidate: config.candidate, canaryPct: config.canaryPct }));
app.get('/api/config', (_, res) => res.json(config));
app.post('/api/config', (req, res) => {
  const b = req.body || {};
  if (b.primary != null) config.primary = String(b.primary).replace(/\/$/, '');
  if (b.candidate != null) config.candidate = String(b.candidate).replace(/\/$/, '');
  if (b.mode) config.mode = b.mode;
  if (b.canaryPct != null) config.canaryPct = Math.max(0, Math.min(1, Number(b.canaryPct)));
  res.json(config);
});
app.get('/api/stats', (_, res) => res.json({ mode: config.mode, canaryPct: config.canaryPct, shadow: stats.shadowReport(), canary: stats.canaryReport() }));
app.post('/api/reset', (_, res) => { stats.reset(); canaryAcc = 0; res.json({ ok: true }); });

app.post('/api/promote', (_, res) => {
  const sh = stats.shadowReport(); const cn = stats.canaryReport();
  const ready = sh.compared >= config.minSamples && (sh.matchRate || 0) >= 0.95 && cn.candidate.errorRate <= config.rollbackErrorRate;
  if (!ready) return res.json({ ok: false, reason: 'кандидат не готов', shadow: sh });
  config.primary = config.candidate; config.candidate = ''; config.mode = 'off'; config.canaryPct = 0;
  stats.event('PROMOTED candidate → primary');
  res.json({ ok: true, primary: config.primary });
});
app.post('/api/rollback', (_, res) => { config.canaryPct = 0; config.mode = 'shadow'; stats.rollback('ручной откат'); res.json({ ok: true }); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

app.all(['/api/products', '/api/products/:id', '/api/orders', '/api/orders/:id'], handle);

const PORT = process.env.PORT || 8094;
if (require.main === module) app.listen(PORT, () => console.log(`shadow-canary on :${PORT} (режим: ${config.mode}, primary: ${config.primary})`));
module.exports = app;
