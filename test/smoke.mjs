// test/smoke.mjs — проверка цифрового двойника.
// (1) детерминизм и реакция спроса на цену (ядро sim);
// (2) поведение сегментов; (3) HTTP: /api/simulate, /api/whatif, /api/run-live
// (реальные заказы на mock-бэкенде), /api/ask (движок rules).
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

const CATALOG = [
  { id: 1, name: 'Красная роза',   price: 1.5, currency: 'EUR', is_featured: true,  stock: 1000 },
  { id: 2, name: 'Жёлтый тюльпан', price: 0.8, currency: 'EUR', is_featured: false, stock: 1000 },
  { id: 3, name: 'Пион',           price: 2.2, currency: 'EUR', is_featured: true,  stock: 1000 },
];
let placed = 0;
const backend = http.createServer((req, res) => {
  const j = (c, o) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
  if (req.url === '/api/products') return j(200, CATALOG);
  if (req.method === 'POST' && req.url === '/api/orders') {
    let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => {
      const p = JSON.parse(b || '{}');
      if (!p.name || !Array.isArray(p.items) || !p.items.length) return j(400, { error: 'bad' });
      const total = p.items.reduce((s, it) => { const pr = CATALOG.find((x) => x.id === it.product_id); return s + (pr ? pr.price * it.quantity : 0); }, 0);
      placed++; j(201, { order_number: 'ORD-' + (1000 + placed), total: Math.round(total * 100) / 100, items: p.items });
    }); return;
  }
  j(404, { error: 'nf' });
});
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const sim = require('../sim.js');

  console.log('ядро: детерминизм и реакция спроса:');
  const a = sim.simulate(CATALOG, { ticks: 24, arrivalRate: 8, seed: 7 });
  const b = sim.simulate(CATALOG, { ticks: 24, arrivalRate: 8, seed: 7 });
  check('один seed → идентичный прогон', JSON.stringify(a.totals) === JSON.stringify(b.totals) && a.totals.arrivals > 0);
  const cheap = sim.simulate(CATALOG, { ticks: 24, arrivalRate: 8, seed: 7, priceMultiplier: 1.0 });
  const dear = sim.simulate(CATALOG, { ticks: 24, arrivalRate: 8, seed: 7, priceMultiplier: 2.5 });
  check('рост цены снижает конверсию', dear.totals.conversion_rate < cheap.totals.conversion_rate);
  check('прогон даёт выручку', cheap.totals.revenue > 0);

  console.log('поведение сегментов:');
  const budget = sim.simulate(CATALOG, { ticks: 30, arrivalRate: 10, seed: 3, onlyPersona: 'budget' });
  const bu = Object.fromEntries(budget.unitsByProduct.map((x) => [x.name, x.units]));
  check('экономный берёт в основном тюльпан', bu['Жёлтый тюльпан'] > bu['Красная роза'] && bu['Жёлтый тюльпан'] > bu['Пион']);
  const romantic = sim.simulate(CATALOG, { ticks: 30, arrivalRate: 10, seed: 3, onlyPersona: 'romantic' });
  const ro = Object.fromEntries(romantic.unitsByProduct.map((x) => [x.name, x.units]));
  check('романтик берёт в основном розы', ro['Красная роза'] > ro['Жёлтый тюльпан'] && ro['Красная роза'] > ro['Пион']);

  // HTTP
  const bport = await listen(backend);
  process.env.BACKEND_URL = `http://localhost:${bport}`;
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const post = async (p, bd) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bd || {}) })).json();

  console.log('HTTP:');
  const h = await (await fetch(base + '/api/health')).json();
  check('движок rule-based', h.engine === 'rules');

  const simr = await post('/api/simulate', { ticks: 20, arrivalRate: 8, seed: 11 });
  check('simulate: есть посетители и выручка', simr.totals.arrivals > 0 && simr.totals.revenue > 0);
  check('simulate: временной ряд по тикам', Array.isArray(simr.series) && simr.series.length === 20);

  const w = await post('/api/whatif', { ticks: 24, arrivalRate: 8, seed: 11, multiplier: 1.5 });
  check('whatif: наценка не повышает конверсию', w.delta_conversion <= 0);
  check('whatif: есть база и сценарий', w.baseline && w.scenario && typeof w.delta_revenue === 'number');

  const live = await post('/api/run-live', { ticks: 20, arrivalRate: 8, seed: 5 });
  check('live: заказы оформлены на бэкенде', live.placed_orders > 0 && live.placed_orders === live.totals.purchases);
  check('live: бэкенд реально принял заказы', placed === live.placed_orders);
  check('live: выданы номера заказов', Array.isArray(live.order_numbers) && live.order_numbers.length === live.placed_orders && /ORD-\d+/.test(live.order_numbers[0]));
  check('live: без ошибок оформления', live.failed_orders === 0);

  console.log('интерпретация (движок rules):');
  const q1 = await post('/api/ask', { message: 'бестселлеры' });
  check('бестселлеры: назван товар', /Роза|роз|Тюльпан|Пион/.test(q1.reply) && q1.engine === 'rules');
  const q2 = await post('/api/ask', { message: 'выручка по сегментам' });
  check('сегменты: назван сегмент', /Романтик|Экономный|Организатор|Зевака/.test(q2.reply));

  srv.close(); backend.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}

main().catch((e) => { console.error(e); process.exit(1); });
