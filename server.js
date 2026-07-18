// server.js — Rosetta: кросс-языковой верификатор портов одного контракта.
// Дифференциально сверяет N реализаций (разные языки/стеки) на эквивалентность
// наблюдаемого поведения; baseline фиксирует принятые расхождения (waiver).
const express = require('express');
const path = require('path');
const runner = require('./runner');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let classify = null;
if (HAS_KEY) { try { classify = require('./judge-llm').classify; } catch (e) { console.error('LLM-классификатор недоступен:', e.message); } }
const ENGINE_NAME = classify ? 'llm' : 'rules';
const sessions = new Map();

function defaultBackends() {
  const raw = process.env.ROSETTA_BACKENDS;
  if (raw) { try { return JSON.parse(raw); } catch (e) { console.error('ROSETTA_BACKENDS невалиден:', e.message); } }
  return [
    { name: 'level1-php', url: 'http://localhost:8081' },
    { name: 'level2-flask', url: 'http://localhost:8082' },
    { name: 'level4-express', url: 'http://localhost:8084' },
    { name: 'level5-react-flask', url: 'http://localhost:8085' },
  ];
}

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backends: defaultBackends().length }));
app.get('/api/backends', (_, res) => res.json({ backends: defaultBackends() }));

app.post('/api/verify', async (req, res) => {
  const b = req.body || {};
  const backends = Array.isArray(b.backends) && b.backends.length ? b.backends : defaultBackends();
  try {
    const run = await runner.runAll(backends, { referenceName: b.referenceName });
    store.setLast(run);
    res.json({ ...run, compare: runner.compare(run, store.getBaseline()) });
  } catch (e) { res.status(502).json({ error: e.message }); }
});

app.get('/api/last', (_, res) => { const l = store.getLast(); l ? res.json(l) : res.status(404).json({ error: 'нет прогонов' }); });
app.post('/api/baseline', (_, res) => { const l = store.getLast(); if (!l) return res.status(400).json({ error: 'сначала верификация' }); store.setBaseline(l); res.json({ ok: true, accepted: l.divergences.length }); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8103;
if (require.main === module) app.listen(PORT, () => console.log(`rosetta on :${PORT} (движок: ${ENGINE_NAME})`));
module.exports = app;
