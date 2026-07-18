// contract-test/run.mjs — consumer-driven contract test.
// Один набор проверок, доказывающий, что бэкенд соответствует единому контракту
// (openapi.yaml). Запускается против ЛЮБОГО уровня или роутера:
//   BACKEND_URL=http://localhost:8002 node contract-test/run.mjs
// Так один тест доказывает взаимозаменяемость всех 7 реализаций.
const BASE = (process.env.BACKEND_URL || 'http://localhost:8080').replace(/\/$/, '');

let passed = 0;
const failures = [];
function check(name, cond) {
  if (cond) { passed++; console.log('  ✓', name); }
  else { failures.push(name); console.log('  ✗', name); }
}
const isNum = (v) => typeof v === 'number' && !Number.isNaN(v);
const isStr = (v) => typeof v === 'string' && v.length > 0;

async function main() {
  console.log(`Контракт-тест против: ${BASE}\n`);

  // 1) health
  const h = await fetch(`${BASE}/api/health`);
  check('GET /api/health → 200', h.status === 200);
  const hb = await h.json().catch(() => ({}));
  check('health.ok === true', hb.ok === true);
  check('health.level — число', isNum(hb.level));
  check('health.stack — строка', isStr(hb.stack));

  // 2) каталог
  const pr = await fetch(`${BASE}/api/products`);
  check('GET /api/products → 200', pr.status === 200);
  const prods = await pr.json().catch(() => null);
  check('products — непустой массив', Array.isArray(prods) && prods.length > 0);
  const p0 = Array.isArray(prods) ? prods[0] : {};
  check('product.id — число', isNum(p0.id));
  check('product.name — строка', isStr(p0.name));
  check('product.price — число', isNum(Number(p0.price)));
  check('product.stock — число', isNum(p0.stock));

  // 3) создание заказа
  const payload = { name: 'Contract Test', phone: '0', email: 'c@t.io', address: 'ул. Тест, 1',
    items: [{ product_id: p0.id || 1, quantity: 1 }] };
  const or = await fetch(`${BASE}/api/orders`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  check('POST /api/orders → 201', or.status === 201);
  const ob = await or.json().catch(() => ({}));
  check('order.order_number — строка (≥8)', isStr(ob.order_number) && ob.order_number.length >= 8);
  check('order.total — число', isNum(ob.total));

  // 4) заказ по токену (round-trip)
  const det = await fetch(`${BASE}/api/orders/${ob.order_number}`);
  check('GET /api/orders/<token> → 200', det.status === 200);
  const db = await det.json().catch(() => ({}));
  check('order.order_number совпадает', db.order && db.order.order_number === ob.order_number);
  check('order.payment_status присутствует', db.order && isStr(db.order.payment_status));
  check('items — непустой массив', Array.isArray(db.items) && db.items.length > 0);
  const it = (db.items || [])[0] || {};
  check('item.product_name — строка', isStr(it.product_name));
  check('item.quantity — число', isNum(it.quantity));
  check('item.line_total — число', isNum(Number(it.line_total)));

  // 5) негативные сценарии
  const bad = await fetch(`${BASE}/api/orders`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: '', items: [] }) });
  check('POST /api/orders (пусто) → 400', bad.status === 400);
  const miss = await fetch(`${BASE}/api/orders/deadbeefdeadbeefdeadbeefdeadbeef`);
  check('GET несуществующего заказа → 404', miss.status === 404);

  console.log(`\nИтог: ${passed} пройдено, ${failures.length} провалено`);
  if (failures.length) { console.log('Провалы:', failures.join('; ')); process.exit(1); }
  console.log('КОНТРАКТ СОБЛЮДЁН ✓');
}

main().catch((e) => { console.error('Ошибка контракт-теста:', e.message); process.exit(1); });
