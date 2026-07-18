// server.js — RAG + память: grounded-ответы по базе знаний магазина и
// персонализированные рекомендации на основе пер-клиентской памяти.
const express = require('express');
const path = require('path');
const contract = require('./contract');
const rag = require('./rag');
const memory = require('./memory');
const knowledge = require('./knowledge');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

memory.load();
const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let llm = null;
if (HAS_KEY) {
  try { llm = require('./advisor-llm'); }
  catch (e) { console.error('LLM-RAG недоступен, используется детерминированный:', e.message); }
}
const ENGINE_NAME = llm ? 'llm' : 'rules';

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL, kb: knowledge.length }));
app.get('/api/kb', (_, res) => res.json({ documents: knowledge.map((d) => ({ id: d.id, topic: d.topic, tags: d.tags })) }));

// grounded-ответ (RAG)
app.post('/api/ask', async (req, res) => {
  const b = req.body || {};
  const customerId = b.customerId || 'anon';
  try {
    const out = llm ? await llm.answer(customerId, b.question || '') : rag.answer(customerId, b.question || '');
    res.json(out);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// память клиента
app.get('/api/memory/:id', (req, res) => res.json(memory.recall(req.params.id)));
app.post('/api/memory/:id', (req, res) => res.json(memory.remember(req.params.id, req.body || {})));
app.delete('/api/memory/:id', (req, res) => { memory.forget(req.params.id); res.json({ ok: true }); });

// персонализированные рекомендации
app.post('/api/recommend', async (req, res) => {
  const customerId = (req.body || {}).customerId || 'anon';
  try {
    const catalog = await contract.listProducts();
    res.json(rag.recommend(customerId, catalog));
  } catch (e) { res.status(502).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8079;
if (require.main === module) {
  app.listen(PORT, () => console.log(`rag-memory on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL})`));
}
module.exports = app;
