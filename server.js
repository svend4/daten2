// server.js — слой наблюдаемости: бенчмарк семи стеков через единый контракт,
// метрики Prometheus и интерпретация результатов (LLM или детерминированная).
const express = require('express');
const path = require('path');
const registry = require('./registry');
const bench = require('./bench');
const store = require('./store');
const metrics = require('./metrics');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advisor = null;
if (HAS_KEY) {
  try { advisor = require('./advisor'); }
  catch (e) { console.error('LLM-аналитик недоступен, используется детерминированный:', e.message); }
}
const ENGINE_NAME = advisor ? 'llm' : 'rules';
const sessions = new Map();

// стамп времени приходит снаружи (в тестах — детерминированно)
async function runBench(opts) {
  const results = await bench.benchAll(registry.levels, opts);
  const run = { at: new Date().toISOString(), opts, results };
  store.set(run);
  return run;
}

app.get('/api/health', (_, res) =>
  res.json({ ok: true, engine: ENGINE_NAME, levels: registry.levels.length, hasRun: !!store.get() }));

app.get('/api/levels', (_, res) => res.json({ levels: registry.levels }));

// запустить бенчмарк по всем стекам
app.post('/api/bench', async (req, res) => {
  const b = req.body || {};
  const opts = {
    path: b.path || '/api/products',
    requests: Math.min(2000, Math.max(1, Number(b.requests) || 100)),
    concurrency: Math.min(100, Math.max(1, Number(b.concurrency) || 10)),
    timeoutMs: Number(b.timeoutMs) || 5000,
  };
  try {
    const run = await runBench(opts);
    res.json({ at: run.at, opts: run.opts, results: run.results, ranked: bench.rank(run.results).map((r) => r.id) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// последний прогон
app.get('/api/results', (_, res) => {
  const run = store.get();
  if (!run) return res.status(404).json({ error: 'бенчмарк ещё не запускался' });
  res.json({ ...run, ranked: bench.rank(run.results).map((r) => r.id) });
});

// метрики Prometheus
app.get('/metrics', (_, res) => res.type('text/plain; version=0.0.4').send(metrics.render()));

// интерпретация результатов
app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  const message = (req.body && req.body.message) || '';
  let session = sessions.get(sid);
  if (!session) { session = {}; sessions.set(sid, session); }
  try {
    const engine = advisor || interpret;
    const out = await engine.ask(session, message);
    res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8074;
if (require.main === module) {
  app.listen(PORT, () => console.log(`observability on :${PORT} (движок: ${ENGINE_NAME}, стеков: ${registry.levels.length})`));
}

module.exports = app;
