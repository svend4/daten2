// server.js — реальные интеграции через адаптеры: платежи (Stripe|mock) и
// эмбеддинги (Voyage|mock). Провайдер выбирается по наличию ключа; без ключа —
// детерминированный mock (демо/тесты работают без сети).
const express = require('express');
const path = require('path');
const payment = require('./payment');
const embeddings = require('./embeddings');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm' : 'rules';
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, payment: payment.name, embeddings: embeddings.provider.name, embed_model: embeddings.provider.model }));
app.get('/api/providers', (_, res) => res.json({ payment: { name: payment.name, real: payment.name !== 'mock' }, embeddings: { name: embeddings.provider.name, model: embeddings.provider.model, real: embeddings.provider.name !== 'mock' } }));

// --- платежи ---
app.post('/api/payments/intent', async (req, res) => {
  const b = req.body || {};
  if (!(Number(b.amount) > 0)) return res.status(400).json({ error: 'amount > 0 обязателен' });
  try { res.status(201).json(await payment.createIntent(Number(b.amount), b.currency, b.orderNumber)); }
  catch (e) { res.status(502).json({ error: e.message }); }
});
app.post('/api/payments/confirm', async (req, res) => {
  try { res.json(await payment.confirm((req.body || {}).intentId)); }
  catch (e) { res.status(400).json({ error: e.message }); }
});
app.get('/api/payments/:id', async (req, res) => {
  try { const i = await payment.get(req.params.id); i ? res.json(i) : res.status(404).json({ error: 'не найден' }); }
  catch (e) { res.status(502).json({ error: e.message }); }
});

// --- эмбеддинги ---
app.post('/api/embed', async (req, res) => {
  const texts = (req.body || {}).texts;
  if (!Array.isArray(texts) || !texts.length) return res.status(400).json({ error: 'texts (массив) обязателен' });
  try { const vectors = await embeddings.provider.embed(texts); res.json({ model: embeddings.provider.model, dim: vectors[0] ? vectors[0].length : 0, vectors }); }
  catch (e) { res.status(502).json({ error: e.message }); }
});
app.post('/api/similarity', async (req, res) => {
  const b = req.body || {};
  if (!b.query || !Array.isArray(b.docs)) return res.status(400).json({ error: 'query и docs обязательны' });
  try { res.json({ query: b.query, provider: embeddings.provider.name, results: await embeddings.rank(b.query, b.docs) }); }
  catch (e) { res.status(502).json({ error: e.message }); }
});

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8101;
if (require.main === module) app.listen(PORT, () => console.log(`integrations on :${PORT} (payment: ${payment.name}, embeddings: ${embeddings.provider.name})`));
module.exports = app;
