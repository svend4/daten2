// test/smoke.mjs — проверка событийной шины (event sourcing).
// Append/seq/replay, свёртка проекций + rebuild, деривация из снимков, SSE, HTTP.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

// mock-бэкенд с изменяемым каталогом (для деривации)
let CATALOG = [{ id: 1, name: 'Роза', price: 1.5, stock: 40 }, { id: 2, name: 'Тюльпан', price: 0.8, stock: 60 }];
const backend = http.createServer((req, res) => {
  if (req.url === '/api/products') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify(CATALOG)); }
  res.writeHead(404); res.end('{}');
});
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const bus = require('../bus.js');
  const projections = require('../projections.js');
  const deriver = require('../deriver.js');

  console.log('event store:');
  bus.reset();
  const e1 = bus.append('OrderPlaced', { order_number: 'ORD-1', total: 3.0 }, 'storefront');
  const e2 = bus.append('OrderPlaced', { order_number: 'ORD-2', total: 5.0 }, 'twin');
  bus.append('OrderStatusChanged', { order_number: 'ORD-1', status: 'shipped' }, 'level');
  check('seq монотонно растёт', e1.seq === 1 && e2.seq === 2 && bus.lastSeq() === 3);
  check('журнал append-only (3 события)', bus.count() === 3);
  check('replay since(1) → хвост', bus.since(1).length === 2 && bus.since(1)[0].seq === 2);
  const snapshot = JSON.stringify(bus.all());
  bus.append('ProductViewed', { product_id: 1 }, 'ui');
  check('прошлые события неизменны', snapshot === JSON.stringify(bus.all().slice(0, 3)));

  console.log('проекции (свёртка) + rebuild:');
  const st = projections.build(bus.all());
  check('выручка = сумма OrderPlaced', st.orders.count === 2 && st.orders.revenue === 8.0);
  check('счётчики по типам', st.byType.OrderPlaced === 2 && st.byType.ProductViewed === 1);
  const st2 = projections.build(bus.all());
  check('rebuild детерминирован (та же свёртка)', JSON.stringify(st) === JSON.stringify(st2));

  console.log('деривация из снимков каталога:');
  const prev = [{ id: 1, name: 'Роза', price: 1.5, stock: 40 }, { id: 2, name: 'Тюльпан', price: 0.8, stock: 60 }];
  const next = [{ id: 1, name: 'Роза', price: 1.7, stock: 35 }, { id: 3, name: 'Пион', price: 2.2, stock: 25 }];
  const derived = deriver.derive(prev, next);
  const types = derived.map((d) => d.type);
  check('StockChanged для розы (40→35)', derived.some((d) => d.type === 'StockChanged' && d.payload.product_id === 1 && d.payload.to === 35));
  check('PriceChanged для розы (1.5→1.7)', derived.some((d) => d.type === 'PriceChanged' && d.payload.from === 1.5 && d.payload.to === 1.7));
  check('ProductAdded (пион) и ProductRemoved (тюльпан)', types.includes('ProductAdded') && types.includes('ProductRemoved'));

  console.log('HTTP + SSE:');
  const bport = await listen(backend);
  process.env.BACKEND_URL = `http://localhost:${bport}`;
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const post = async (p, b) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })).json();

  const ing = await post('/api/events', { type: 'OrderPlaced', payload: { order_number: 'ORD-9', total: 10 }, source: 'test' });
  check('ingest события', ing.seq >= 1 && ing.type === 'OrderPlaced');
  let proj = await (await fetch(base + '/api/projections')).json();
  check('живые проекции обновились', proj.orders.count >= 1 && proj.orders.revenue >= 10);

  // снимок 1 → ProductAdded ×2; меняем каталог; снимок 2 → Stock/Price/Added/Removed
  const s1 = await post('/api/snapshot');
  check('первый снимок: ProductAdded по всем', s1.derived === 2 && s1.types.ProductAdded === 2);
  CATALOG = [{ id: 1, name: 'Роза', price: 1.9, stock: 30 }, { id: 3, name: 'Пион', price: 2.2, stock: 25 }];
  const s2 = await post('/api/snapshot');
  check('второй снимок деривирует изменения', s2.types.StockChanged >= 1 && s2.types.PriceChanged >= 1 && s2.types.ProductAdded >= 1 && s2.types.ProductRemoved >= 1);

  const reb = await post('/api/rebuild', {});
  check('rebuild из журнала = живые проекции', reb.eventCount === (await (await fetch(base + '/api/projections')).json()).eventCount);

  // SSE
  const ctrl = new AbortController();
  const sse = await fetch(base + '/api/stream', { signal: ctrl.signal });
  const reader = sse.body.getReader();
  const { value } = await reader.read();
  const chunk = new TextDecoder().decode(value);
  ctrl.abort();
  check('SSE-поток открыт (text/event-stream)', /event-stream/.test(sse.headers.get('content-type') || '') && /connected|data/.test(chunk));

  const q = await post('/api/ask', { message: 'какая выручка?' });
  check('ask (rules) про выручку', /выручк|заказ/i.test(q.reply) && q.engine === 'rules');

  srv.close(); backend.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
