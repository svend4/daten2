// test/smoke.mjs — проверка рынка агентов (детерминированные стратегии).
// Сходимость при наличии ZOPA, отсутствие сделки без ZOPA, соблюдение пола,
// оформление сделки через контракт, HTTP.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;
process.env.MAX_DISCOUNT = '0.2';

const CATALOG = [
  { id: 1, name: 'Красная роза', price: 2.0, currency: 'EUR', stock: 500 },
  { id: 2, name: 'Тюльпан', price: 1.0, currency: 'EUR', stock: 500 },
];
let placed = 0;
const backend = http.createServer((req, res) => {
  const j = (c, o) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
  if (req.url === '/api/products') return j(200, CATALOG);
  if (req.method === 'POST' && req.url === '/api/orders') {
    let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => { const p = JSON.parse(b || '{}'); placed++; j(201, { order_number: 'ORD-' + (1000 + placed), total: 0, items: p.items }); }); return;
  }
  j(404, {});
});
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const agents = require('../agents.js');
  const negotiation = require('../negotiation.js');
  const rose = CATALOG[0]; // P=2.0, floor=1.6 при maxDiscount 0.2

  console.log('ядро торга:');
  // ZOPA есть: бюджет 2.0 ≥ пол 1.6 → сделка
  let s = agents.makeSeller(rose, 1), b = agents.makeBuyer(2.0, rose);
  let r = negotiation.run(s, b);
  check('пол продавца = 1.6', s.floor === 1.6);
  check('есть сделка при бюджете ≥ пола', !!r.deal);
  check('цена сделки не ниже пола', r.deal.agreed_unit >= 1.6);
  check('цена сделки не выше прайса', r.deal.agreed_unit <= 2.0);
  check('скидка в пределах политики (≤20%)', r.deal.discount_pct <= 20 + 1e-9 && r.deal.discount_pct >= 0);
  check('транскрипт заканчивается accept', r.transcript[r.transcript.length - 1].type === 'accept');
  check('стороны чередуются', r.transcript.some((m) => m.from === 'seller') && r.transcript.some((m) => m.from === 'buyer'));

  // ZOPA нет: бюджет 1.0 < пол 1.6 → нет сделки
  s = agents.makeSeller(rose, 1); b = agents.makeBuyer(1.0, rose);
  r = negotiation.run(s, b);
  check('нет сделки при бюджете < пола', r.deal === null && r.transcript[r.transcript.length - 1].type === 'reject');

  // опт двигает пол ниже (доп. скидка)
  const sBulk = agents.makeSeller(rose, 20); // bulk
  check('крупный опт снижает пол', sBulk.floor < 1.6);

  console.log('HTTP + оформление сделки:');
  const bport = await listen(backend);
  process.env.BACKEND_URL = `http://localhost:${bport}`;
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const post = async (p, body) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();

  const h = await (await fetch(base + '/api/health')).json();
  check('движок rule-based', h.engine === 'rules');

  const before = placed;
  const deal = await post('/api/negotiate', { productId: 1, quantity: 3, buyerBudget: 2.0 });
  check('HTTP: достигнута сделка', !!deal.deal && deal.deal.agreed_unit >= 1.6);
  check('HTTP: заказ оформлен через контракт', deal.order && /ORD-/.test(deal.order.order_number) && placed === before + 1);
  check('HTTP: посчитан итог сделки', deal.deal.agreed_total === Math.round(deal.deal.agreed_unit * 3 * 100) / 100);

  const before2 = placed;
  const noDeal = await post('/api/negotiate', { productId: 1, quantity: 1, buyerBudget: 1.0 });
  check('HTTP: без сделки заказ не оформлен', noDeal.deal === null && !noDeal.order && placed === before2);

  const q = await post('/api/ask', { message: 'какая средняя скидка?' });
  check('HTTP ask (rules) про скидку', /скидк/i.test(q.reply) && q.engine === 'rules');

  srv.close(); backend.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
