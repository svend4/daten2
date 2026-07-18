// server.js — Pact для ИИ-агентов: верификация агента против контракта поведения,
// генеративная проверка на семействе формулировок, регрессии при смене модели.
const express = require('express');
const path = require('path');
const pact = require('./pact');
const runner = require('./runner');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let judge = null;
if (HAS_KEY) { try { judge = require('./judge-llm').judge; } catch (e) { console.error('LLM-судья недоступен:', e.message); } }
const ENGINE_NAME = judge ? 'llm' : 'rules';
const DEFAULT_AGENT = (process.env.AGENT_URL || 'http://localhost:8070').replace(/\/$/, '');
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, agent: DEFAULT_AGENT, expectations: pact.expectations.length }));
app.get('/api/pact', (_, res) => res.json(pact));

app.post('/api/verify', async (req, res) => {
  const b = req.body || {};
  const target = (b.agentUrl || DEFAULT_AGENT).replace(/\/$/, '');
  try {
    const run = await runner.runAll(target, { path: b.path, judge });
    store.setLast(run);
    res.json({ ...run, compare: runner.compare(run, store.getBaseline()) });
  } catch (e) { res.status(502).json({ error: e.message }); }
});

app.get('/api/last', (_, res) => { const l = store.getLast(); l ? res.json(l) : res.status(404).json({ error: 'нет прогонов' }); });
app.post('/api/baseline', (_, res) => { const l = store.getLast(); if (!l) return res.status(400).json({ error: 'сначала верификация' }); store.setBaseline(l); res.json({ ok: true, held: l.held, total: l.total }); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8102;
if (require.main === module) app.listen(PORT, () => console.log(`agent-pact on :${PORT} (движок: ${ENGINE_NAME}, агент: ${DEFAULT_AGENT})`));
module.exports = app;
