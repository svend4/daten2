// server.js — Distillation-as-deployment: модель-ученик как версионируемый сервис
// с канареечным гейтом качества и авто-откатом при просадке согласия ниже SLO.
const express = require('express');
const path = require('path');
const model = require('./model');
const data = require('./data');
const teacher = require('./teacher');
const { createRegistry } = require('./registry');
const pipeline = require('./pipeline');
const interpret = require('./interpret');

const app = express();
app.use(express.json({ limit: '8mb' }));
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let diagnose = null;
if (HAS_KEY) { try { diagnose = require('./judge-llm').diagnose; } catch (e) { console.error('LLM-диагност недоступен:', e.message); } }
const ENGINE_NAME = diagnose ? 'llm' : 'rules';

const registry = createRegistry();
const sessions = new Map();
let ver = 0;

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, floor: pipeline.FLOOR, ...registry.stats() }));

// обучить и выкатить новую версию через канареечный гейт.
// body: {epochs?, trainSeed?, trainSize?, classes?} — обучение из данных учителя;
// или {artifact} — готовый артефакт весов.
app.post('/api/deploy', (req, res) => {
  const b = req.body || {};
  const version = b.version || 'v' + (++ver);
  const artifact = b.artifact || model.train(data.generate(b.trainSize || 300, b.trainSeed == null ? 1 : b.trainSeed, { classes: b.classes }), { epochs: b.epochs == null ? 200 : b.epochs, classes: b.classes });
  const evalSet = b.evalSet || data.generate(b.evalSize || 200, b.evalSeed == null ? 99 : b.evalSeed, { classes: b.evalClasses });
  const result = pipeline.deploy(registry, version, artifact, evalSet);
  res.json(result);
});

app.get('/api/models', (_, res) => res.json({ models: registry.all().map((m) => ({ version: m.version, state: m.state, canaryAgreement: m.canaryAgreement })), production: registry.production(), incidents: registry.incidents() }));
app.get('/api/production', (_, res) => { const p = registry.production(); p ? res.json(registry.get(p)) : res.status(404).json({ error: 'нет продакшн-модели' }); });

app.post('/api/predict', (req, res) => {
  const p = registry.production();
  if (!p) return res.status(404).json({ error: 'нет продакшн-модели' });
  const predict = model.predictor(registry.get(p).artifact);
  const out = predict((req.body || {}).text || '');
  res.json({ version: p, ...out, teacher: teacher.label((req.body || {}).text || '') });
});

// живой мониторинг дрейфа: {samples?} или сгенерировать order-heavy и пр.
app.post('/api/monitor', (req, res) => {
  const b = req.body || {};
  const samples = b.samples || data.generate(b.size || 150, b.seed == null ? 555 : b.seed, { classes: b.classes });
  const r = pipeline.monitor(registry, samples);
  res.json(r);
});

app.post('/api/ask', (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  if (!sessions.has(sid)) sessions.set(sid, {});
  try { const out = interpret.ask(registry, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8109;
if (require.main === module) app.listen(PORT, () => console.log(`distill-deploy on :${PORT} (движок: ${ENGINE_NAME}, SLO ${pipeline.FLOOR})`));
module.exports = app;
