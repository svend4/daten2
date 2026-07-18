// server.js — разговорная витрина.
// LLM-движок (Claude API) при наличии ANTHROPIC_API_KEY, иначе детерминированный фолбэк.
const express = require('express');
const path = require('path');
const nlu = require('./nlu');
const { BACKEND_URL } = require('./shop');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let llm = null;
if (HAS_KEY) {
  try { llm = require('./llm'); }
  catch (e) { console.error('LLM-движок недоступен, используется фолбэк:', e.message); }
}
const ENGINE_NAME = llm ? 'llm' : 'rules';

// in-memory сессии диалога
const sessions = new Map();

app.get('/api/health', (_, res) =>
  res.json({ ok: true, engine: ENGINE_NAME, backend: BACKEND_URL }));

app.post('/api/chat', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  const message = (req.body && req.body.message) || '';
  let session = sessions.get(sid);
  if (!session) { session = {}; sessions.set(sid, session); }
  try {
    const engine = llm || nlu;
    const out = await engine.handle(session, message);
    res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME, cart: out.cart || null });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

const PORT = process.env.PORT || 8070;
if (require.main === module) {
  app.listen(PORT, () => console.log(`ai-storefront on :${PORT} (движок: ${ENGINE_NAME}, backend: ${BACKEND_URL})`));
}
module.exports = app;
