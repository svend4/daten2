// server.js — property-based тестирование инвариантов контракта.
// Генерирует случайные валидные входы, проверяет свойства против цели и сжимает
// контрпример при провале.
const express = require('express');
const path = require('path');
const runner = require('./runner');
const properties = require('./properties');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm' : 'rules';
const DEFAULT_TARGET = (process.env.TARGET_URL || 'http://localhost:8080').replace(/\/$/, '');
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, target: DEFAULT_TARGET, properties: properties.length }));
app.get('/api/properties', (_, res) => res.json({ properties: properties.map((p) => ({ id: p.id, name: p.name })) }));

app.post('/api/run', async (req, res) => {
  const b = req.body || {};
  const target = (b.target || DEFAULT_TARGET).replace(/\/$/, '');
  try {
    const report = await runner.runAll(target, { iterations: Math.min(500, Math.max(1, Number(b.iterations) || 40)), seed: Number(b.seed) || 1 });
    store.set(report);
    res.json(report);
  } catch (e) { res.status(502).json({ error: e.message }); }
});
app.get('/api/last', (_, res) => { const l = store.get(); l ? res.json(l) : res.status(404).json({ error: 'нет прогонов' }); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8098;
if (require.main === module) app.listen(PORT, () => console.log(`property-tests on :${PORT} (движок: ${ENGINE_NAME}, target: ${DEFAULT_TARGET})`));
module.exports = app;
