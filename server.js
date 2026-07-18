// server.js — автономный управляющий: замкнутая петля наблюдение→анализ→действие
// через единый контракт, с эскалацией человеку и предохранителями.
const express = require('express');
const path = require('path');
const contract = require('./contract');
const store = require('./store');
const engine = require('./engine');
const policy = require('./policy');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advisor = null;
if (HAS_KEY) {
  try { advisor = require('./advisor'); }
  catch (e) { console.error('LLM-советник недоступен, используется детерминированный:', e.message); }
}
const ENGINE_NAME = advisor ? 'llm' : 'rules';
const sessions = new Map();

async function observe() {
  const products = await contract.listProducts();
  return store.recordSnapshot(products, Date.now());
}

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL, ...store.state() }));
app.get('/api/state', (_, res) => res.json(store.state()));
app.get('/api/config', (_, res) => res.json(policy));

// изменить политику автономии (kill-switch/сухой прогон/пороги)
app.post('/api/config', (req, res) => {
  const b = req.body || {};
  if (typeof b.dryRun === 'boolean') policy.dryRun = b.dryRun;
  if (b.autoThreshold !== undefined) policy.autoThreshold = Math.max(0, Math.min(100, Number(b.autoThreshold)));
  if (b.maxActionsPerCycle !== undefined) policy.maxActionsPerCycle = Math.max(1, Number(b.maxActionsPerCycle));
  if (b.cooldownCycles !== undefined) policy.cooldownCycles = Math.max(0, Number(b.cooldownCycles));
  res.json(policy);
});

app.post('/api/pause', (_, res) => { store.pause(); res.json({ ok: true, paused: true }); });
app.post('/api/resume', (_, res) => { store.resume(); res.json({ ok: true, paused: false }); });

app.post('/api/snapshot', async (_, res) => {
  try { const s = await observe(); res.json({ ok: true, t: s.t, products: s.products.length, snapshots: store.allSnapshots().length }); }
  catch (e) { res.status(502).json({ error: e.message }); }
});

// один цикл управления (при observe:true сначала снять снимок)
app.post('/api/cycle', async (req, res) => {
  try {
    if (req.body && req.body.observe) await observe();
    const summary = await engine.cycle();
    res.json(summary);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/pending', (_, res) => res.json({ pending: store.pendingList }));
app.get('/api/ledger', (_, res) => res.json({ ledger: store.ledgerList.slice(-100) }));
app.get('/api/audit', (_, res) => res.json({ audit: store.auditList.slice(-100) }));

app.post('/api/approve/:id', async (req, res) => { res.json(await engine.approve(req.params.id)); });
app.post('/api/reject/:id', (req, res) => { res.json(engine.reject(req.params.id, (req.body || {}).note)); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  const message = (req.body && req.body.message) || '';
  let session = sessions.get(sid);
  if (!session) { session = {}; sessions.set(sid, session); }
  try {
    const eng = advisor || interpret;
    const out = await eng.ask(session, message);
    res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8077;
const LOOP_MS = Number(process.env.LOOP_MS || 0); // 0 = автопетля выключена
if (require.main === module) {
  app.listen(PORT, () => console.log(`autonomous-manager on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL}, dryRun: ${policy.dryRun})`));
  if (LOOP_MS > 0) {
    const tick = () => observe().then(() => engine.cycle()).then((s) => console.log('цикл:', JSON.stringify(s))).catch((e) => console.error('цикл не удался:', e.message));
    setInterval(tick, LOOP_MS);
  }
}

module.exports = app;
