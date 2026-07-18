// test/smoke.mjs — проверка разговорной витрины на детерминированном движке.
// Поднимает mock-бэкенд единого контракта, запускает сервер БЕЗ ANTHROPIC_API_KEY
// (движок rules) и проигрывает диалог: каталог → добавление → оформление → заказ.
import http from 'node:http';
import assert from 'node:assert';

// --- mock-бэкенд единого контракта магазина --------------------------------
const PRODUCTS = [
  { id: 1, name: 'Красная роза', price: 1.5, currency: 'EUR', stock: 40, is_featured: true, category_name: 'Розы' },
  { id: 2, name: 'Жёлтый тюльпан', price: 0.8, currency: 'EUR', stock: 60, is_featured: false, category_name: 'Тюльпаны' },
  { id: 3, name: 'Пион', price: 2.2, currency: 'EUR', stock: 25, is_featured: true, category_name: 'Пионы' },
];
const orders = [];
let orderSeq = 1000;

const backend = http.createServer((req, res) => {
  const send = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)); };
  if (req.method === 'GET' && req.url === '/api/products') return send(200, PRODUCTS);
  if (req.method === 'POST' && req.url === '/api/orders') {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      const p = JSON.parse(body || '{}');
      if (!p.name || !Array.isArray(p.items) || !p.items.length) return send(400, { error: 'name и items обязательны' });
      const total = p.items.reduce((s, it) => {
        const prod = PRODUCTS.find((x) => x.id === it.product_id);
        return s + (prod ? prod.price * it.quantity : 0);
      }, 0);
      const order = { order_number: 'ORD-' + ++orderSeq, total, status: 'new', items: p.items, customer: { name: p.name } };
      orders.push(order);
      send(201, order);
    });
    return;
  }
  const m = req.url.match(/^\/api\/orders\/(.+)$/);
  if (req.method === 'GET' && m) {
    const o = orders.find((x) => x.order_number === decodeURIComponent(m[1]));
    return o ? send(200, o) : send(404, { error: 'not found' });
  }
  send(404, { error: 'not found' });
});

// --- запуск ----------------------------------------------------------------
async function listen(server, port) {
  return new Promise((resolve) => server.listen(port, () => resolve(server.address().port)));
}

let failures = 0;
function check(name, cond) {
  if (cond) console.log('  ✓ ' + name);
  else { console.error('  ✗ ' + name); failures++; }
}

async function chat(base, sessionId, message) {
  const r = await fetch(base + '/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, message }),
  });
  return r.json();
}

async function main() {
  const backendPort = await listen(backend, 0);
  process.env.BACKEND_URL = `http://localhost:${backendPort}`;
  delete process.env.ANTHROPIC_API_KEY; // гарантируем детерминированный движок

  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv, 0);
  const base = `http://localhost:${port}`;
  const sid = 'smoke-1';

  console.log('health:');
  const health = await (await fetch(base + '/api/health')).json();
  check('ok', health.ok === true);
  check('движок rule-based', health.engine === 'rules');
  check('backend виден', health.backend === process.env.BACKEND_URL);

  console.log('диалог:');
  const cat = await chat(base, sid, 'Покажи каталог');
  check('каталог содержит розу', /Красная роза/.test(cat.reply));
  check('каталог содержит цену', /1\.50 €/.test(cat.reply));

  const filt = await chat(base, sid, 'есть рекомендуемые до 2 евро?');
  check('фильтр показал розу (1.50, featured)', /Красная роза/.test(filt.reply));
  check('фильтр скрыл пион (2.20 > 2)', !/Пион/.test(filt.reply));

  const add1 = await chat(base, sid, 'Добавьте 2 розы');
  check('добавлены 2 розы', /Добавил: Красная роза × 2/.test(add1.reply));
  check('корзина в ответе', Array.isArray(add1.cart) && add1.cart.length === 1);

  const add2 = await chat(base, sid, 'добавьте 1 пион');
  check('добавлен пион', /Пион/.test(add2.reply) && add2.cart.length === 2);

  const cart = await chat(base, sid, 'что в корзине?');
  check('корзина: 2 позиции', /Красная роза × 2/.test(cart.reply) && /Пион × 1/.test(cart.reply));
  check('корзина: итог 5.20', /5\.20 €/.test(cart.reply)); // 2*1.5 + 2.2

  const checkout = await chat(base, sid, 'оформить заказ');
  check('спрашивает имя', /имя/i.test(checkout.reply));

  const done = await chat(base, sid, 'Стефан');
  check('заказ оформлен', /оформлен/i.test(done.reply));
  check('выдан номер заказа', /ORD-\d+/.test(done.reply));
  check('корзина очищена', Array.isArray(done.cart) && done.cart.length === 0);
  check('заказ дошёл до бэкенда', orders.length === 1);
  check('в заказе верное имя', orders[0].customer.name === 'Стефан');
  check('в заказе 2 позиции', orders[0].items.length === 2);

  srv.close();
  backend.close();

  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}

main().catch((e) => { console.error(e); process.exit(1); });
