// server.js — Twin-in-loop governor: контур MPC-безопасности. Предложенное действие
// автономного управляющего прогоняется через цифровой двойник и допускается в прод
// только при безопасном и выгодном прогнозе; иначе блок/эскалация + рекомендация.
const express = require('express');
const path = require('path');
const sim = require('./sim');
const governor = require('./governor');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json({ limit: '2mb' }));
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let rule = null;
if (HAS_KEY) { try { rule = require('./judge-llm').rule; } catch (e) { console.error('LLM-арбитр недоступен:', e.message); } }
const ENGINE_NAME = rule ? 'llm' : 'rules';
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, ...store.stats() }));
app.get('/api/state', (_, res) => res.json(store.getState()));
app.post('/api/reset', (_, res) => { store.reset(); res.json({ ok: true, state: store.getState() }); });

// сухая симуляция действия (без записи решения)
app.post('/api/simulate', (req, res) => {
  const b = req.body || {};
  try { res.json(sim.rollForward(store.getState(), b.action || { type: 'noop' }, { steps: b.steps })); }
  catch (e) { res.status(400).json({ error: e.message }); }
});

// предложить действие губернатору: симуляция → решение (+ LLM-арбитр при эскалации)
app.post('/api/propose', async (req, res) => {
  const b = req.body || {};
  if (!b.action || !b.action.type) return res.status(400).json({ error: 'нужен action.type' });
  try {
    const ev = governor.evaluate(store.getState(), b.action, { steps: b.steps, alternatives: b.alternatives, config: b.config });
    if (ev.decision === 'escalate' && rule) { try { ev.arbiter = await rule(ev); } catch (e) { ev.arbiterError = e.message; } }
    store.record({ decision: ev.decision, reason: ev.reason, action: ev.action, violations: ev.violations, uplift: ev.uplift, simulated: ev.simulated, baseline: ev.baseline, recommendation: ev.recommendation });
    res.json(ev);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/log', (_, res) => res.json({ log: store.log(), stats: store.stats() }));

app.post('/api/ask', (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  if (!sessions.has(sid)) sessions.set(sid, {});
  try { const out = interpret.ask(sessions.get(sid), (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8110;
if (require.main === module) app.listen(PORT, () => console.log(`twin-governor on :${PORT} (движок: ${ENGINE_NAME})`));
module.exports = app;
