// server.js — control-plane (портал): единая точка входа со статусом всех сервисов
// стенда, агрегацией по категориям и ссылками на дашборды.
const express = require('express');
const path = require('path');
const registry = require('./registry');
const monitor = require('./monitor');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm' : 'rules';
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, services: registry.services.length }));
app.get('/api/services', (_, res) => res.json({ services: registry.services.map((s) => ({ id: s.id, name: s.name, cat: s.cat, dash: s.dash })) }));

// живой опрос статусов
app.get('/api/status', async (_, res) => {
  try { const snap = await monitor.pollAll(registry.services); store.set(snap); res.json(snap); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8099;
const POLL_MS = Number(process.env.POLL_MS || 0);
if (require.main === module) {
  app.listen(PORT, () => console.log(`control-plane on :${PORT} (сервисов: ${registry.services.length})`));
  if (POLL_MS > 0) setInterval(() => monitor.pollAll(registry.services).then(store.set).catch(() => {}), POLL_MS);
}
module.exports = app;
