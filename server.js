// server.js — Carbon arbitrage: углеродно-осознанное планирование отложимых
// ИИ-нагрузок во времени и регионах с измеримым выигрышем CO2/€.
const express = require('express');
const path = require('path');
const grid = require('./grid');
const arbitrage = require('./arbitrage');
const invariants = require('./invariants');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json({ limit: '4mb' }));
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advise = null;
if (HAS_KEY) { try { advise = require('./judge-llm').advise; } catch (e) { console.error('LLM-советник недоступен:', e.message); } }
const ENGINE_NAME = advise ? 'llm' : 'rules';
const T = Number(process.env.SLOTS || 12);
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, slots: T, regions: grid.REGIONS }));
app.get('/api/grid', (_, res) => res.json(grid.generate(T)));

app.post('/api/schedule', async (req, res) => {
  const b = req.body || {};
  if (!Array.isArray(b.jobs) || !b.jobs.length) return res.status(400).json({ error: 'нужен jobs[]' });
  const g = grid.generate(T);
  const opts = { weightCarbon: b.weightCarbon == null ? 1 : Number(b.weightCarbon), capacityPerCell: b.capacityPerCell == null ? Infinity : Number(b.capacityPerCell) };
  const p = arbitrage.plan(b.jobs, g, opts);
  const jobsById = Object.fromEntries(b.jobs.map((j) => [j.id, j]));
  p.invariants = invariants.check(jobsById, g, p, opts.capacityPerCell);
  store.setLast(p);
  if (advise) { try { p.advice = await advise(p); } catch (e) { p.adviceError = e.message; } }
  res.json(p);
});

app.get('/api/last', (_, res) => { const l = store.getLast(); l ? res.json(l) : res.status(404).json({ error: 'нет планов' }); });

app.post('/api/ask', (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  if (!sessions.has(sid)) sessions.set(sid, {});
  try { const out = interpret.ask(sessions.get(sid), (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8107;
if (require.main === module) app.listen(PORT, () => console.log(`carbon-arbitrage on :${PORT} (движок: ${ENGINE_NAME}, слотов: ${T})`));
module.exports = app;
