// server.js — полиглот-бенчмарк: прогон по семи стекам и генерация публикуемого
// перф-отчёта (Markdown/HTML) как воспроизводимого исследовательского артефакта.
const express = require('express');
const path = require('path');
const stacksMod = require('./stacks');
const runner = require('./runner');
const report = require('./report');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm' : 'rules';
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, stacks: stacksMod.stacks.length }));
app.get('/api/stacks', (_, res) => res.json({ stacks: stacksMod.stacks.map((s) => ({ id: s.id, name: s.name, language: s.language, storage: s.storage, watts: s.watts })) }));

app.post('/api/run', async (req, res) => {
  const b = req.body || {};
  const opts = {
    path: b.endpoint || '/api/products',
    requests: Math.min(5000, Math.max(1, Number(b.requests) || 100)),
    concurrency: Math.min(100, Math.max(1, Number(b.concurrency) || 10)),
    warmup: Math.min(100, Math.max(0, Number(b.warmup) ?? 5)),
  };
  try {
    const results = await runner.runAll(stacksMod.stacks, opts);
    const meta = { endpoint: opts.path, requests: opts.requests, concurrency: opts.concurrency, warmup: opts.warmup, at: new Date().toISOString() };
    store.set({ results, meta });
    res.json({ meta, results });
  } catch (e) { res.status(502).json({ error: e.message }); }
});

app.get('/api/report.md', (_, res) => {
  const run = store.get();
  if (!run) return res.status(404).type('text/plain').send('# Отчёт пуст — сначала прогон (/api/run)');
  res.type('text/markdown; charset=utf-8').set('Content-Disposition', 'inline; filename="polyglot-benchmark.md"').send(report.markdown(run.results, run.meta));
});
app.get('/api/report.html', (_, res) => {
  const run = store.get();
  if (!run) return res.status(404).send('<p>Отчёт пуст — сначала прогон.</p>');
  res.type('text/html; charset=utf-8').send(report.html(run.results, run.meta));
});
app.get('/api/results', (_, res) => { const l = store.get(); l ? res.json(l) : res.status(404).json({ error: 'нет прогонов' }); });

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8100;
if (require.main === module) app.listen(PORT, () => console.log(`polyglot-benchmark on :${PORT} (стеков: ${stacksMod.stacks.length})`));
module.exports = app;
