// server.js — Backend-plugin marketplace: реестр сменных бэкендов с гейтом
// соответствия контракту и router-совместимым каталогом сертифицированных.
const express = require('express');
const path = require('path');
const { createRegistry } = require('./registry');
const interpret = require('./interpret');

const app = express();
app.use(express.json({ limit: '2mb' }));
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let review = null;
if (HAS_KEY) { try { review = require('./judge-llm').review; } catch (e) { console.error('LLM-ревьюер недоступен:', e.message); } }
const ENGINE_NAME = review ? 'llm' : 'rules';

const registry = createRegistry();
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, ...registry.stats() }));

// опубликовать/зарегистрировать плагин (валидация манифеста + живой гейт контракта)
app.post('/api/plugins', async (req, res) => {
  try {
    const rec = await registry.publish(req.body || {});
    if (review && rec.state !== 'rejected') { try { rec.review = await review(rec.manifest); } catch (e) { rec.reviewError = e.message; } }
    res.status(rec.state === 'certified' ? 201 : 400).json(rec);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/plugins', (_, res) => res.json({ plugins: registry.ids().map((id) => ({ id, active: registry.active(id), versions: registry.forId(id).map((r) => ({ version: r.version, state: r.state, yanked: r.yanked, score: r.score })) })), stats: registry.stats() }));
app.get('/api/plugins/:id', (req, res) => { const v = registry.forId(req.params.id); v.length ? res.json({ id: req.params.id, active: registry.active(req.params.id), versions: v }) : res.status(404).json({ error: 'нет плагина' }); });
app.post('/api/plugins/:id/yank', (req, res) => { const r = registry.yank(req.params.id, (req.body || {}).version); r.error ? res.status(404).json(r) : res.json(r); });

// каталог для авто-регистрации в роутере (только сертифицированные активные)
app.get('/api/catalog', (_, res) => res.json({ backends: registry.catalog() }));

app.post('/api/ask', (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  if (!sessions.has(sid)) sessions.set(sid, {});
  try { const out = interpret.ask(registry, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8108;
if (require.main === module) app.listen(PORT, () => console.log(`plugin-marketplace on :${PORT} (движок: ${ENGINE_NAME})`));
module.exports = app;
