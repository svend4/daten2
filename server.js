// server.js — Vision: анализ изображений, поиск букета по фото и авто-теги.
// Детерминированное цветовое ядро (PNG) + опциональный Claude-vision (любой формат).
const express = require('express');
const path = require('path');
const contract = require('./contract');
const vision = require('./vision');

const app = express();
app.use(express.json({ limit: '8mb' })); // изображения в base64
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let llm = null;
if (HAS_KEY) {
  try { llm = require('./vision-llm'); }
  catch (e) { console.error('Claude-vision недоступен, используется цветовое ядро:', e.message); }
}
const ENGINE_NAME = llm ? 'llm' : 'rules';

const decodeB64 = (s) => Buffer.from(String(s || '').replace(/^data:[^,]+,/, ''), 'base64');

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL }));

// анализ изображения → цвет/тип/теги (+ Claude-описание при ключе)
app.post('/api/analyze', async (req, res) => {
  const b = req.body || {};
  try {
    const analysis = vision.analyzeBuffer(decodeB64(b.imageBase64));
    const out = { ...analysis, description: vision.describe(analysis), engine: 'rules' };
    if (llm) { try { out.llm = await llm.analyze(String(b.imageBase64).replace(/^data:[^,]+,/, ''), b.mediaType || 'image/png'); } catch (e) { out.llm = { error: e.message }; } }
    res.json(out);
  } catch (e) { res.status(400).json({ error: e.message }); }
});

// поиск букета по фото
app.post('/api/search-by-photo', async (req, res) => {
  const b = req.body || {};
  try {
    const analysis = vision.analyzeBuffer(decodeB64(b.imageBase64));
    const catalog = await contract.listProducts();
    res.json({ analysis: { colorName: analysis.colorName, flowerRoot: analysis.flowerRoot, tags: analysis.tags, dominant: analysis.dominant }, results: vision.matchProducts(analysis, catalog).slice(0, 6) });
  } catch (e) { res.status(400).json({ error: e.message }); }
});

// авто-теги/описание для карточки товара
app.post('/api/autotag', async (req, res) => {
  const b = req.body || {};
  try {
    if (llm) return res.json(await llm.analyze(String(b.imageBase64).replace(/^data:[^,]+,/, ''), b.mediaType || 'image/png'));
    const analysis = vision.analyzeBuffer(decodeB64(b.imageBase64));
    res.json({ flower: analysis.flowerRoot, color: analysis.colorName, tags: analysis.tags, description: vision.describe(analysis), engine: 'rules' });
  } catch (e) { res.status(400).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8088;
if (require.main === module) {
  app.listen(PORT, () => console.log(`vision on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL})`));
}
module.exports = app;
