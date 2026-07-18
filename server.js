// server.js — событийная шина (event sourcing).
// Принимает доменные события (push), деривирует их из снимков контракта (pull),
// держит проекции-read-models (свёртка) и раздаёт единый поток через SSE.
const express = require('express');
const path = require('path');
const bus = require('./bus');
const projections = require('./projections');
const deriver = require('./deriver');
const contract = require('./contract');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let advisor = null;
if (HAS_KEY) { try { advisor = require('./advisor'); } catch (e) { console.error('LLM-аналитик недоступен:', e.message); } }
const ENGINE_NAME = advisor ? 'llm' : 'rules';
const sessions = new Map();

// живые проекции обновляются на каждое событие
let state = projections.empty();
bus.subscribe((e) => { projections.apply(state, e); });
let lastSnapshot = null;

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL, events: bus.count(), types: bus.KNOWN }));

// публикация события (push от уровня/сервиса)
app.post('/api/events', (req, res) => {
  const b = req.body || {};
  if (!b.type) return res.status(400).json({ error: 'type обязателен' });
  const e = bus.append(b.type, b.payload, b.source || 'ingest');
  res.status(201).json(e);
});

// журнал / replay
app.get('/api/events', (req, res) => res.json({ from: Number(req.query.from || 0), events: req.query.from ? bus.since(req.query.from) : bus.all().slice(-200), lastSeq: bus.lastSeq() }));

// проекции (read-models)
app.get('/api/projections', (_, res) => res.json(state));

// пересборка проекций из журнала (event sourcing)
app.post('/api/rebuild', (_, res) => { state = projections.build(bus.all()); res.json({ ok: true, ...state }); });

// снимок каталога → деривация событий
app.post('/api/snapshot', async (_, res) => {
  try {
    const products = await contract.listProducts();
    const snap = products.map((p) => ({ id: p.id, name: p.name, price: Number(p.price), stock: Number(p.stock) }));
    const derived = lastSnapshot ? deriver.derive(lastSnapshot, snap) : snap.map((p) => ({ type: 'ProductAdded', payload: { product_id: p.id, name: p.name, price: p.price, stock: p.stock } }));
    for (const d of derived) bus.append(d.type, d.payload, 'deriver');
    lastSnapshot = snap;
    res.json({ ok: true, derived: derived.length, types: derived.reduce((a, d) => ((a[d.type] = (a[d.type] || 0) + 1), a), {}) });
  } catch (e) { res.status(502).json({ error: e.message }); }
});

// единый поток событий (SSE) — для аналитики и ИИ
app.get('/api/stream', (req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
  res.write(': connected\n\n');
  const unsub = bus.subscribe((e) => res.write(`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`));
  req.on('close', () => unsub());
});

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  let session = sessions.get(sid); if (!session) { session = {}; sessions.set(sid, session); }
  try {
    const out = advisor ? await advisor.ask(session, (req.body || {}).message || '', state) : interpret.ask(session, (req.body || {}).message || '', state);
    res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8097;
if (require.main === module) app.listen(PORT, () => console.log(`event-bus on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL})`));
module.exports = app;
