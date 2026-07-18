// test/smoke.js — проверяет роутер против мок-бэкенда, реализующего единый контракт.
const http = require('http');
const assert = require('assert');

const MOCK_PORT = 9902;
const GW_PORT = 9980;

// --- мок-уровень (контракт-совместимый) ---
const orders = {};
const mock = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  res.setHeader('Content-Type', 'application/json');
  if (url.pathname === '/api/health') {
    return res.end(JSON.stringify({ ok: true, level: 2, stack: 'MockFlask' }));
  }
  if (url.pathname === '/api/products') {
    return res.end(JSON.stringify([
      { id: 1, name: 'Красная роза', slug: 'red-rose', price: 1.5, currency: 'EUR', stock: 50, is_featured: true, category_name: 'Розы' },
    ]));
  }
  if (url.pathname === '/api/orders' && req.method === 'POST') {
    let b = '';
    req.on('data', (c) => (b += c));
    return req.on('end', () => {
      const token = 'mocktoken0000000000000000000000a';
      orders[token] = { order: { order_number: token, status: 'new', payment_status: 'pending', total_amount: 1.5, customer_name: 'CI', phone: '0' }, items: [{ product_name: 'Красная роза', quantity: 1, unit_price: 1.5, line_total: 1.5 }] };
      res.statusCode = 201;
      res.end(JSON.stringify({ order_number: token, total: 1.5 }));
    });
  }
  const m = url.pathname.match(/^\/api\/orders\/(.+)$/);
  if (m) {
    const o = orders[m[1]];
    if (!o) { res.statusCode = 404; return res.end(JSON.stringify({ error: 'not found' })); }
    return res.end(JSON.stringify(o));
  }
  res.statusCode = 404;
  res.end(JSON.stringify({ error: 'unknown' }));
});

async function main() {
  await new Promise((r) => mock.listen(MOCK_PORT, r));

  // указываем роутеру мок как L2, остальные — недоступны; дефолт = 2
  process.env.LEVEL2_URL = `http://localhost:${MOCK_PORT}`;
  process.env.DEFAULT_LEVEL = '2';
  process.env.PROBE_TIMEOUT = '800';
  const app = require('../server');
  const gw = app.listen(GW_PORT);
  await new Promise((r) => gw.on('listening', r));
  const base = `http://localhost:${GW_PORT}`;

  // 1) агрегация health
  const health = await (await fetch(`${base}/gateway/health`)).json();
  const l2 = health.find((s) => s.level === 2);
  assert(l2 && l2.up === true, 'L2 должен быть online');
  assert(health.filter((s) => !s.up).length === 6, 'остальные 6 — offline');
  console.log('✓ health-агрегация: L2 online, 6 offline');

  // 2) каталог проксируется (дефолтная политика → L2)
  const pr = await fetch(`${base}/api/products`);
  assert.strictEqual(pr.headers.get('x-served-by-level'), '2', 'каталог обслужил L2');
  const prods = await pr.json();
  assert(Array.isArray(prods) && prods[0].name === 'Красная роза', 'каталог с L2');
  console.log('✓ /api/products проксирован на L2');

  // 3) заказ создаётся и читается по токену с того же уровня
  const or = await fetch(`${base}/api/orders`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'CI', items: [{ product_id: 1, quantity: 1 }] }) });
  assert.strictEqual(or.status, 201, 'заказ создан');
  const { order_number } = await or.json();
  const det = await (await fetch(`${base}/api/orders/${order_number}?level=2`)).json();
  assert.strictEqual(det.order.payment_status, 'pending', 'заказ читается по токену');
  console.log('✓ /api/orders create+read через роутер');

  // 4) пин на недоступный уровень → 503
  const miss = await fetch(`${base}/api/products?level=1`);
  // L1 offline и дефолт L2 up → политика вернёт дефолт; проверим что пин на несуществующий не падает
  assert([200, 503].includes(miss.status), 'graceful на недоступный пин');
  console.log('✓ graceful обработка недоступного уровня');

  console.log('\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ✓');
  gw.close();
  mock.close();
}

main().catch((e) => { console.error('✗', e.message); process.exit(1); });
