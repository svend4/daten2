// server.js — цифровой двойник магазина.
// Синтетические покупатели генерируют спрос через единый контракт: offline-симуляция
// и what-if по ценам, либо «живой» режим с реальными заказами (кормит роутер/управляющего).
const express = require('express');
const path = require('path');
const contract = require('./contract');
const sim = require('./sim');
const runner = require('./runner');
const store = require('./store');
const personas = require('./personas');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advisor = null;
if (HAS_KEY) {
  try { advisor = require('./advisor'); }
  catch (e) { console.error('LLM-аналитик недоступен, используется детерминированный:', e.message); }
}
const ENGINE_NAME = advisor ? 'llm' : 'rules';
const sessions = new Map();

const params = (b) => ({
  ticks: Math.min(500, Math.max(1, Number(b.ticks) || 24)),
  arrivalRate: Math.min(500, Math.max(0, Number(b.arrivalRate) ?? 6)),
  seed: Number.isFinite(Number(b.seed)) ? Number(b.seed) : 42,
  priceMultiplier: Math.min(5, Math.max(0.1, Number(b.priceMultiplier) || 1)),
  onlyPersona: b.onlyPersona || undefined,
});

app.get('/api/health', (_, res) =>
  res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL, hasRun: !!store.get() }));

app.get('/api/personas', (_, res) => res.json({ personas }));

// offline-симуляция (без побочных эффектов)
app.post('/api/simulate', async (req, res) => {
  const p = params(req.body || {});
  try {
    const catalog = await contract.listProducts();
    const r = sim.simulate(catalog, p);
    store.set({ mode: 'offline', ...r });
    res.json({ mode: 'offline', params: r.params, totals: r.totals, unitsByProduct: r.unitsByProduct, bySegment: r.bySegment, series: r.series });
  } catch (e) { res.status(502).json({ error: e.message }); }
});

// what-if: базовый сценарий против ценового множителя
app.post('/api/whatif', async (req, res) => {
  const p = params(req.body || {});
  const multiplier = Math.min(5, Math.max(0.1, Number((req.body || {}).multiplier) || 1.1));
  try {
    const catalog = await contract.listProducts();
    const base = sim.simulate(catalog, { ...p, priceMultiplier: 1 });
    const scen = sim.simulate(catalog, { ...p, priceMultiplier: multiplier });
    const whatif = {
      multiplier,
      baseline: base.totals,
      scenario: scen.totals,
      delta_revenue: Math.round((scen.totals.revenue - base.totals.revenue) * 100) / 100,
      delta_conversion: Math.round((scen.totals.conversion_rate - base.totals.conversion_rate) * 1000) / 1000,
    };
    store.set({ mode: 'whatif', ...scen, whatif });
    res.json(whatif);
  } catch (e) { res.status(502).json({ error: e.message }); }
});

// живой режим: реальные заказы через контракт
app.post('/api/run-live', async (req, res) => {
  const p = params(req.body || {});
  try {
    const r = await runner.runLive({ ...p, maxOrders: Number((req.body || {}).maxOrders) || 500 });
    store.set(r);
    res.json(r);
  } catch (e) { res.status(502).json({ error: e.message }); }
});

app.get('/api/state', (_, res) => {
  const run = store.get();
  if (!run) return res.status(404).json({ error: 'ещё не запускалось' });
  res.json(run);
});

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  const message = (req.body && req.body.message) || '';
  let session = sessions.get(sid);
  if (!session) { session = {}; sessions.set(sid, session); }
  try {
    const engine = advisor || interpret;
    const out = await engine.ask(session, message);
    res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8075;
if (require.main === module) {
  app.listen(PORT, () => console.log(`digital-twin on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL})`));
}

module.exports = app;
