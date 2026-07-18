// server.js — авто-эвалы: прогон контрактных и поведенческих кейсов против цели,
// scorecard, baseline/регрессии и LLM-as-judge для оценки качества.
const express = require('express');
const path = require('path');
const runner = require('./runner');
const cases = require('./cases');
const scorecard = require('./scorecard');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const TARGET_URL = (process.env.TARGET_URL || process.env.BACKEND_URL || 'http://localhost:8080').replace(/\/$/, '');
const CHAT_URL = (process.env.CHAT_URL || 'http://localhost:8070').replace(/\/$/, '');
const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let judge = null;
if (HAS_KEY) { try { judge = require('./judge-llm').judge; } catch (e) { console.error('LLM-judge недоступен:', e.message); } }
const ENGINE_NAME = judge ? 'llm-judge' : 'rules';
const sessions = new Map();

// счётчик для детерминированных «at» (без Date в критичных местах — но здесь ок)
let runSeq = 0;
const at = () => `run-${++runSeq}`;

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, target: TARGET_URL, chat: CHAT_URL, hasBaseline: !!scorecard.getBaseline() }));
app.get('/api/cases', (_, res) => res.json({ contract: cases.contract.map((c) => ({ id: c.id, name: c.name, weight: c.weight })), behavior: cases.behavior.map((c) => ({ id: c.id, name: c.name, weight: c.weight })) }));

// прогон контрактного набора
app.post('/api/run', async (req, res) => {
  const target = (req.body && req.body.target) || TARGET_URL;
  try { const card = scorecard.record(await runner.runContract(target, at)); res.json({ ...card, compare: scorecard.compare(card, scorecard.getBaseline()) }); }
  catch (e) { res.status(502).json({ error: e.message }); }
});

// прогон поведенческого набора (против витрины /api/chat)
app.post('/api/run-behavior', async (req, res) => {
  const target = (req.body && req.body.target) || CHAT_URL;
  try { const card = scorecard.record(await runner.runBehavior(target, at)); res.json(card); }
  catch (e) { res.status(502).json({ error: e.message }); }
});

app.get('/api/scorecard', (_, res) => { const l = scorecard.getLast(); l ? res.json({ ...l, compare: scorecard.compare(l, scorecard.getBaseline()) }) : res.status(404).json({ error: 'нет прогонов' }); });
app.post('/api/baseline', (_, res) => { const l = scorecard.getLast(); if (!l) return res.status(400).json({ error: 'сначала прогон' }); res.json({ ok: true, baseline: scorecard.setBaseline(l).score }); });

// LLM-as-judge оценка произвольного ответа
app.post('/api/judge', async (req, res) => {
  if (!judge) return res.status(400).json({ error: 'LLM-judge требует ANTHROPIC_API_KEY' });
  const b = req.body || {};
  try { res.json(await judge({ prompt: b.prompt || '', response: b.response || '', rubric: b.rubric })); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8090;
if (require.main === module) {
  app.listen(PORT, () => console.log(`evals on :${PORT} (движок: ${ENGINE_NAME}, target: ${TARGET_URL})`));
}
module.exports = app;
