// server.js — ИИ-управляющий. Периодически снимает каталог через единый контракт,
// строит аналитику (детерминированное ядро) и отвечает на вопросы владельца
// (LLM-советник при ANTHROPIC_API_KEY, иначе детерминированный Q&A).
const express = require('express');
const path = require('path');
const contract = require('./contract');
const store = require('./store');
const analytics = require('./analytics');
const qa = require('./qa');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advisor = null;
if (HAS_KEY) {
  try { advisor = require('./advisor'); }
  catch (e) { console.error('LLM-советник недоступен, используется детерминированный Q&A:', e.message); }
}
const ENGINE_NAME = advisor ? 'llm' : 'rules';

store.load();
const sessions = new Map();

// снять текущий снимок каталога в ряд
async function snapshot() {
  const products = await contract.listProducts();
  return store.record(products, Date.now());
}

app.get('/api/health', (_, res) =>
  res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL, snapshots: store.all().length }));

app.post('/api/snapshot', async (_, res) => {
  try {
    const snap = await snapshot();
    res.json({ ok: true, t: snap.t, products: snap.products.length, snapshots: store.all().length });
  } catch (e) { res.status(502).json({ error: e.message }); }
});

app.get('/api/report', (_, res) => res.json(analytics.report(store.all())));

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  const message = (req.body && req.body.message) || '';
  let session = sessions.get(sid);
  if (!session) { session = {}; sessions.set(sid, session); }
  try {
    const engine = advisor || qa;
    const out = await engine.ask(session, message);
    res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8071;
const POLL_MS = Number(process.env.POLL_MS || 0); // 0 = автоснятие выключено

if (require.main === module) {
  app.listen(PORT, () => console.log(`ai-manager on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL})`));
  if (POLL_MS > 0) {
    const tick = () => snapshot().then((s) => console.log('снимок:', s.products.length, 'товаров')).catch((e) => console.error('снимок не удался:', e.message));
    tick();
    setInterval(tick, POLL_MS);
  }
}

module.exports = app;
