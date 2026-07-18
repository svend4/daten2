// server.js — контракт-codegen + CDC (Pact).
// Отдаёт спецификацию и пакт, генерирует типизированные клиенты и верифицирует
// любого провайдера-уровня против пакта (машинная гарантия взаимозаменяемости).
const express = require('express');
const path = require('path');
const spec = require('./spec');
const pact = require('./pact');
const codegen = require('./codegen');
const verifier = require('./verify');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm' : 'rules';
const DEFAULT_TARGET = (process.env.TARGET_URL || 'http://localhost:8080').replace(/\/$/, '');
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, target: DEFAULT_TARGET, langs: codegen.langs }));
app.get('/api/spec', (_, res) => res.json(spec));
app.get('/api/pact', (_, res) => res.json(pact));

// генерация клиента: /api/codegen?lang=js|python|ts-types
app.get('/api/codegen', (req, res) => {
  const out = codegen.generate((req.query.lang || 'js').toString());
  if (out.error) return res.status(400).json(out);
  res.type('text/plain; charset=utf-8').send(out.code);
});
app.get('/api/codegen.json', (req, res) => res.json(codegen.generate((req.query.lang || 'js').toString())));

// верификация провайдера против пакта
app.post('/api/verify', async (req, res) => {
  const target = ((req.body && req.body.target) || DEFAULT_TARGET).replace(/\/$/, '');
  try { const report = await verifier.verify(target); store.set(report); res.json(report); }
  catch (e) { res.status(502).json({ error: e.message }); }
});
app.get('/api/last', (_, res) => { const l = store.get(); l ? res.json(l) : res.status(404).json({ error: 'нет верификаций' }); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8095;
if (require.main === module) app.listen(PORT, () => console.log(`contract-cdc on :${PORT} (движок: ${ENGINE_NAME}, target: ${DEFAULT_TARGET})`));
module.exports = app;
