// server.js — дистилляция: обучение локального ученика на разметке учителя и
// дешёвый офлайн-инференс. Ученик работает БЕЗ ключа и без сети.
const express = require('express');
const path = require('path');
const distillMod = require('./distill');
const student = require('./student');
const teacher = require('./teacher');
const store = require('./store');

const app = express();
app.use(express.json({ limit: '4mb' }));
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm-teacher' : 'rules-teacher';

// обучаем ученика при старте (детерминированно)
function ensureTrained() {
  if (!store.get()) store.set({ ...distillMod.distill({ n: 1200, seed: 42, epochs: 600, lr: 0.8 }), at: 'boot' });
  return store.get();
}
ensureTrained();

app.get('/api/health', (_, res) => {
  const s = store.get();
  res.json({ ok: true, engine: ENGINE_NAME, labels: teacher.LABELS, agreement: s ? s.metrics.agreement : null });
});

app.get('/api/metrics', (_, res) => res.json((store.get() || {}).metrics || {}));

// переобучить с параметрами
app.post('/api/train', (req, res) => {
  const b = req.body || {};
  const out = distillMod.distill({ n: Math.min(3000, Math.max(50, Number(b.n) || 500)), seed: Number(b.seed) || 42, epochs: Math.min(1000, Math.max(20, Number(b.epochs) || 250)), lr: Number(b.lr) || 0.5 });
  store.set({ ...out, at: 'manual' });
  res.json(out.metrics);
});

// инференс ученика (быстрый, локальный)
app.post('/api/classify', (req, res) => {
  const text = (req.body || {}).text || '';
  const s = ensureTrained();
  const pred = student.predict(s.model, text);
  res.json({ ...pred, teacher: teacher.label(text), agree: pred.label === teacher.label(text) });
});

// метка учителя (эталон)
app.post('/api/teacher', (req, res) => res.json({ label: teacher.label((req.body || {}).text || '') }));

// экспорт компактной модели (переносимые веса)
app.get('/api/model', (_, res) => {
  const s = ensureTrained();
  const exp = student.exportModel(s.model);
  res.json({ labels: exp.labels, dim: exp.dim, nonzero_weights: exp.W.reduce((a, r) => a + r.length, 0), model: exp });
});

const PORT = process.env.PORT || 8089;
if (require.main === module) {
  app.listen(PORT, () => console.log(`distillation on :${PORT} (учитель: ${ENGINE_NAME}, согласие: ${(store.get() || {}).metrics?.agreement})`));
}
module.exports = app;
