// server.js — семантический поиск и рекомендации по каталогу.
// Индексирует товары через единый контракт и обслуживает поиск по смыслу и
// «похожие товары». Вектор запроса кодирует LLM (Claude) при ANTHROPIC_API_KEY,
// иначе детерминированный энкодер по смысловым осям.
const express = require('express');
const path = require('path');
const contract = require('./contract');
const store = require('./index-store');
const enc = require('./encoder');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let llm = null;
if (HAS_KEY) {
  try { llm = require('./embedder-llm'); }
  catch (e) { console.error('LLM-энкодер недоступен, используется детерминированный:', e.message); }
}
const ENGINE_NAME = llm ? 'llm' : 'rules';
const encodeQuery = llm ? llm.encodeText : null;

app.get('/api/health', (_, res) =>
  res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL, indexed: store.size() }));

app.get('/api/axes', (_, res) => res.json({ axes: enc.AXES.map((a) => ({ key: a.key, label: a.label })) }));

app.post('/api/index', async (_, res) => {
  try { const n = await store.build(); res.json({ ok: true, indexed: n }); }
  catch (e) { res.status(502).json({ error: e.message }); }
});

app.post('/api/search', async (req, res) => {
  const query = (req.body && req.body.query) || '';
  const top = Number((req.body && req.body.top) || 5);
  try {
    if (!store.size()) await store.build();
    const out = await store.search(query, top, encodeQuery);
    res.json({ ...out, engine: ENGINE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/similar/:id', async (req, res) => {
  try {
    if (!store.size()) await store.build();
    const out = store.similar(req.params.id, Number(req.query.top || 3));
    if (!out) return res.status(404).json({ error: 'товар не найден' });
    res.json(out);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8072;
if (require.main === module) {
  store.build().then((n) => console.log(`проиндексировано товаров: ${n}`)).catch((e) => console.error('индексация отложена:', e.message));
  app.listen(PORT, () => console.log(`ai-search on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL})`));
}

module.exports = app;
