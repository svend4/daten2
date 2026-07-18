// server.js — файрвол для ИИ-агентов с инструментами.
// Стоит между недоверенным вводом покупателя и инструментами магазина: проверяет
// ввод (prompt-injection), вызовы инструментов (злоупотребление) и вывод (утечки),
// и умеет безопасно оформлять заказ через контракт.
const express = require('express');
const path = require('path');
const guard = require('./guard');
const policy = require('./policy');
const store = require('./store');
const contract = require('./contract');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
let judge = null;
if (HAS_KEY) {
  try { judge = require('./judge-llm').judge; }
  catch (e) { console.error('LLM-судья недоступен, работают детекторы:', e.message); }
}
const ENGINE_NAME = judge ? 'llm' : 'rules';
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL }));
app.get('/api/policy', (_, res) => res.json(policy));
app.get('/api/log', (_, res) => res.json({ recent: store.recent(50), stats: store.stats() }));

// проверка ввода покупателя
app.post('/api/guard/input', async (req, res) => {
  const d = await guard.guardInput((req.body || {}).text || '', judge);
  store.record(d, { text: ((req.body || {}).text || '').slice(0, 120) });
  res.json(d);
});

// проверка предлагаемого вызова инструмента
app.post('/api/guard/tool', (req, res) => {
  const b = req.body || {};
  const d = guard.guardTool(b.tool, b.input || {});
  store.record(d, { tool: b.tool });
  res.json(d);
});

// проверка вывода агента (утечки)
app.post('/api/guard/output', (req, res) => {
  const d = guard.guardOutput((req.body || {}).text || '');
  store.record(d);
  res.json(d);
});

// защищённое оформление заказа: ввод + инструмент, затем контракт
app.post('/api/protected/order', async (req, res) => {
  const b = req.body || {};
  const report = {};
  if (b.customerText) {
    const gi = await guard.guardInput(b.customerText, judge);
    store.record(gi, { text: String(b.customerText).slice(0, 120) });
    report.input = gi;
    if (gi.action === 'block') return res.status(403).json({ refused: true, reason: 'ввод покупателя заблокирован', report });
  }
  const gt = guard.guardTool('create_order', { name: b.name, items: b.items });
  store.record(gt);
  report.tool = gt;
  if (gt.action === 'block') return res.status(403).json({ refused: true, reason: 'вызов create_order заблокирован', report });

  try {
    const order = await contract.createOrder(gt.clamped);
    res.json({ ok: true, order, clamped: gt.action === 'allow-clamped', report });
  } catch (e) {
    res.status(502).json({ error: e.message, report });
  }
});

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  const message = (req.body && req.body.message) || '';
  let session = sessions.get(sid);
  if (!session) { session = {}; sessions.set(sid, session); }
  try {
    const out = interpret.ask(session, message);
    res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8076;
if (require.main === module) {
  app.listen(PORT, () => console.log(`agent-firewall on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL})`));
}

module.exports = app;
