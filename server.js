// server.js — рынок агентов: покупатель-агент ↔ продавец-переговорщик торгуются по
// протоколу A2A и при сделке оформляют заказ через единый контракт.
const express = require('express');
const path = require('path');
const contract = require('./contract');
const agents = require('./agents');
const negotiation = require('./negotiation');
const policy = require('./policy');
const store = require('./store');
const interpret = require('./interpret');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const HAS_KEY = !!process.env.ANTHROPIC_API_KEY;
const ENGINE_NAME = HAS_KEY ? 'llm' : 'rules';
const sessions = new Map();

app.get('/api/health', (_, res) => res.json({ ok: true, engine: ENGINE_NAME, backend: contract.BACKEND_URL, policy }));
app.get('/api/catalog', async (_, res) => {
  try { res.json({ products: await contract.listProducts() }); }
  catch (e) { res.status(502).json({ error: e.message }); }
});
app.get('/api/history', (_, res) => res.json({ recent: store.recent(), stats: store.stats() }));

// запустить переговоры между агентами
app.post('/api/negotiate', async (req, res) => {
  const b = req.body || {};
  const quantity = Math.max(1, Number(b.quantity) || 1);
  try {
    const catalog = await contract.listProducts();
    const product = catalog.find((p) => String(p.id) === String(b.productId)) || catalog[0];
    if (!product) return res.status(404).json({ error: 'товар не найден' });
    const seller = agents.makeSeller(product, quantity);
    const budget = b.buyerBudget != null ? Number(b.buyerBudget) : Number(product.price); // по умолчанию готов к прайсу
    const buyer = agents.makeBuyer(budget, product);

    const { deal, transcript } = negotiation.run(seller, buyer);

    let order = null;
    if (deal) {
      try {
        order = await contract.createOrder({ name: `agent-deal-${Date.now()}`, items: [{ product_id: product.id, quantity }] });
        deal.agreed_total = Math.round(deal.agreed_unit * quantity * 100) / 100;
      } catch (e) { order = { error: e.message }; }
    }
    const entry = { product: product.name, productId: product.id, quantity, buyerBudget: budget, deal, order, transcript };
    store.record(entry);
    res.json(entry);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/ask', async (req, res) => {
  const sid = (req.body && req.body.sessionId) || 'default';
  const message = (req.body && req.body.message) || '';
  let session = sessions.get(sid);
  if (!session) { session = {}; sessions.set(sid, session); }
  try { const out = interpret.ask(session, message); res.json({ reply: out.reply, engine: out.engine || ENGINE_NAME }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 8078;
if (require.main === module) {
  app.listen(PORT, () => console.log(`agent-market on :${PORT} (движок: ${ENGINE_NAME}, backend: ${contract.BACKEND_URL})`));
}
module.exports = app;
