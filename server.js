// server.js — Adversarial twin: эволюционный red-team, ищущий сценарии, ломающие
// ИИ-агента/политику. В отличие от digital-twin (нормальный спрос) — состязательный
// поиск по пространству атак с фитнесом по нарушениям.
const express = require('express');
const path = require('path');
const search = require('./search');
const tactics = require('./tactics');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let proposeAttack = null;
if (HAS_KEY) { try { proposeAttack = require('./judge-llm').proposeAttack; } catch (e) { console.error('LLM-генератор атак недоступен:', e.message); } }
const ENGINE_NAME = proposeAttack ? 'llm' : 'rules';
const DEFAULT_AGENT = (process.env.AGENT_URL || 'http://localhost:8070').replace(/\/$/, '');
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, agent: DEFAULT_AGENT, tactics: tactics.ids.length }));
app.get('/api/tactics', (_, res) => res.json({ tactics: tactics.TACTICS.map((t) => ({ id: t.id, category: t.category })) }));

app.post('/api/hunt', async (req, res) => {
  const b = req.body || {};
  const target = (b.agentUrl || DEFAULT_AGENT).replace(/\/$/, '');
  try {
    const run = await search.hunt(target, { generations: b.generations, pop: b.pop, seed: b.seed, path: b.path });
    run.agent = target;
    store.setLast(run);
    res.json(run);
  } catch (e) { res.status(502).json({ error: e.message }); }
});

app.get('/api/last', (_, res) => { const l = store.getLast(); l ? res.json(l) : res.status(404).json({ error: 'нет прогонов' }); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  if (!sessions.has(sid)) sessions.set(sid, {});
  try { const out = interpret.ask(sessions.get(sid), (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8105;
if (require.main === module) app.listen(PORT, () => console.log(`adversarial-twin on :${PORT} (движок: ${ENGINE_NAME}, цель: ${DEFAULT_AGENT})`));
module.exports = app;
