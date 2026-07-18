// server.js — chaos-харнесс: инъекция сбоев в уровни, устойчивый фронт с failover,
// прогон chaos-экспериментов с проверкой гипотез SLO.
const express = require('express');
const path = require('path');
const targetsMod = require('./targets');
const resilient = require('./resilient');
const runner = require('./runner');
const load = require('./load');
const experiments = require('./experiments');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm' : 'rules';
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, targets: targetsMod.targets.length }));
app.get('/api/targets', (_, res) => res.json({ targets: targetsMod.targets.map((t) => ({ id: t.id, name: t.name, fault: t.fault })) }));
app.get('/api/experiments', (_, res) => res.json({ experiments: experiments.map((e) => ({ id: e.id, name: e.name, expectSlo: e.expectSlo, hypothesis: e.hypothesis })) }));

// ручная инъекция/снятие сбоя
app.post('/api/faults/:id', (req, res) => { targetsMod.setFault(req.params.id, req.body || {}); res.json({ ok: true, targets: targetsMod.targets.map((t) => ({ id: t.id, fault: t.fault })) }); });
app.post('/api/faults/clear', (_, res) => { targetsMod.clearFaults(); res.json({ ok: true }); });

// прогон всех chaos-экспериментов
app.post('/api/run', async (req, res) => {
  const b = req.body || {};
  try { const report = await runner.runAll({ requests: Math.min(500, Number(b.requests) || 40), concurrency: Math.min(50, Number(b.concurrency) || 8) }); store.set(report); res.json(report); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

// разовая нагрузка через устойчивый фронт (с текущими сбоями)
app.post('/api/loadtest', async (req, res) => {
  const b = req.body || {};
  try { res.json(await load.run(() => resilient.request(targetsMod.targets, { method: 'GET', path: '/api/products' }), { requests: Number(b.requests) || 40, concurrency: Number(b.concurrency) || 8 })); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

// устойчивый прокси контракта (демонстрирует failover вживую)
async function proxy(req, res) {
  const r = await resilient.request(targetsMod.targets, { method: req.method, path: req.originalUrl, body: req.body });
  if (!r.ok) return res.status(503).json({ error: 'все уровни недоступны' });
  res.status(r.status).set('X-Served-By', r.servedBy).set('X-Failover', String(!!r.failover)).json(r.body);
}
app.all(['/api/products', '/api/products/:id', '/api/orders', '/api/orders/:id'], proxy);

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8096;
if (require.main === module) app.listen(PORT, () => console.log(`chaos-harness on :${PORT} (движок: ${ENGINE_NAME}, уровней: ${targetsMod.targets.length})`));
module.exports = app;
