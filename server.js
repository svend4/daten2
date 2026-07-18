// server.js — Counterfactual AI-ops ledger: append-only хэш-цепь операционных
// решений ИИ + off-policy оценка «а что заработала бы другая политика».
const express = require('express');
const path = require('path');
const { createLedger } = require('./ledger');
const ope = require('./ope');
const policies = require('./policies');
const interpret = require('./interpret');

const app = express();
app.use(express.json({ limit: '4mb' }));
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advise = null;
if (HAS_KEY) { try { advise = require('./judge-llm').advise; } catch (e) { console.error('LLM-советник недоступен:', e.message); } }
const ENGINE_NAME = advise ? 'llm' : 'rules';

const ledger = createLedger();
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, decisions: ledger.state().length, resolved: ledger.resolvedCount(), policies: policies.names() }));

// залогировать решение: {domain, context, actions:[{id,cost,latency,predicted,...}], chosen, propensity, ts?}
app.post('/api/decision', (req, res) => {
  const b = req.body || {};
  if (!b.chosen || !Array.isArray(b.actions) || !b.actions.length) return res.status(400).json({ error: 'нужны actions[] и chosen' });
  const id = ledger.decision(b);
  res.json({ id });
});

// зафиксировать исход: {id, reward}
app.post('/api/resolve', (req, res) => {
  const b = req.body || {};
  if (!b.id || b.reward == null) return res.status(400).json({ error: 'нужны id и reward' });
  ledger.outcome(b.id, Number(b.reward));
  res.json({ ok: true, id: b.id });
});

app.get('/api/ledger', (_, res) => { const s = ledger.state(); res.json({ decisions: s.slice(-200), total: s.length, resolved: ledger.resolvedCount(), integrity: ledger.verify() }); });
app.get('/api/verify-chain', (_, res) => res.json(ledger.verify()));

// off-policy оценка: {policies?:[names], domain?}
app.post('/api/evaluate', async (req, res) => {
  const b = req.body || {};
  let s = ledger.state().filter((d) => d.reward != null);
  if (b.domain) s = s.filter((d) => d.domain === b.domain);
  if (!s.length) return res.status(400).json({ error: 'нет решений с исходом' });
  const cmp = ope.comparePolicies(s, b.policies);
  if (advise) { try { cmp.advice = await advise(cmp); } catch (e) { cmp.adviceError = e.message; } }
  res.json(cmp);
});

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  if (!sessions.has(sid)) sessions.set(sid, {});
  try { const out = interpret.ask(ledger, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8104;
if (require.main === module) app.listen(PORT, () => console.log(`ops-ledger on :${PORT} (движок: ${ENGINE_NAME})`));
module.exports = app;
