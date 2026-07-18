// server.js — A2A settlement: атомарный расчётный слой для сделок агент-агенту.
// Двойная запись (масса денег сохраняется), эскроу (reserve→capture/release),
// saga-атомарный многоплечевой клиринг, идемпотентность, реверс.
const express = require('express');
const path = require('path');
const { createBook } = require('./book');
const { createEngine } = require('./settlement');
const invariants = require('./invariants');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let adjudicate = null;
if (HAS_KEY) { try { adjudicate = require('./judge-llm').adjudicate; } catch (e) { console.error('LLM-арбитр недоступен:', e.message); } }
const ENGINE_NAME = adjudicate ? 'llm' : 'rules';

const book = createBook();
const engine = createEngine(book);
let initialTotal = 0;
const sessions = new Map();
const ctx = () => ({ book, engine, get initialTotal() { return initialTotal; } });

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, accounts: book.accounts().length, settlements: engine.all().length }));

app.post('/api/accounts', (req, res) => {
  const b = req.body || {};
  if (!b.id) return res.status(400).json({ error: 'нужен id' });
  const existed = !!book.get(b.id);
  const a = book.open(b.id, b.initial);
  if (!existed) initialTotal = book.totalMoney();
  res.json({ account: { id: a.id, balance: a.balance, held: a.held } });
});
app.get('/api/accounts', (_, res) => res.json({ accounts: book.snapshot(), total: book.totalMoney() }));

// эскроу
app.post('/api/escrow/reserve', (req, res) => { const b = req.body || {}; const id = book.reserve(b.account, Number(b.amount)); id ? res.json({ holdId: id }) : res.status(400).json({ error: 'недостаточно доступных средств' }); });
app.post('/api/escrow/capture', (req, res) => { const b = req.body || {}; book.capture(b.holdId, b.to) ? res.json({ ok: true }) : res.status(400).json({ error: 'резерв не найден/уже использован' }); });
app.post('/api/escrow/release', (req, res) => { const b = req.body || {}; book.release(b.holdId) ? res.json({ ok: true }) : res.status(400).json({ error: 'резерв не найден' }); });

// атомарный расчёт
app.post('/api/settle', (req, res) => {
  const b = req.body || {};
  if (!b.id || !Array.isArray(b.legs) || !b.legs.length) return res.status(400).json({ error: 'нужны id и legs[]' });
  const rec = engine.settle(b);
  res.json({ settlement: rec, invariants: invariants.check(book, engine, initialTotal) });
});
app.post('/api/reverse', (req, res) => { const b = req.body || {}; const r = engine.reverse(b.settlementId, b.revId); res.json({ result: r, invariants: invariants.check(book, engine, initialTotal) }); });

app.get('/api/settlements', (_, res) => res.json({ settlements: engine.all().slice(-200), byState: engine.byState() }));
app.get('/api/verify-invariants', (_, res) => res.json(invariants.check(book, engine, initialTotal)));

app.post('/api/ask', (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  if (!sessions.has(sid)) sessions.set(sid, {});
  try { const out = interpret.ask(ctx(), (req.body || {}).message || ''); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8106;
if (require.main === module) app.listen(PORT, () => console.log(`a2a-settlement on :${PORT} (движок: ${ENGINE_NAME})`));
module.exports = app;
