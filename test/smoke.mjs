// test/smoke.mjs — проверка codegen + CDC (Pact).
// Генерация клиентов, верификация исправного и сломанного провайдеров, типовые матчеры.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

// исправный провайдер (удовлетворяет пакту)
function goodProvider() {
  const products = [{ id: 1, name: 'Роза', price: 1.5 }, { id: 2, name: 'Тюльпан', price: 0.8 }];
  const orders = {}; let seq = 1000;
  return http.createServer((req, res) => {
    const j = (c, o) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
    if (req.url === '/api/health') return j(200, { ok: true, level: 1 });
    if (req.url === '/api/products') return j(200, products);
    if (req.method === 'POST' && req.url === '/api/orders') {
      let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => { const p = JSON.parse(b || '{}'); if (!p.items || !p.items.length) return j(400, { error: 'items' }); const t = 'ORD-' + ++seq; orders[t] = { order_number: t, total: 3.0 }; j(201, orders[t]); }); return;
    }
    const m = req.url.match(/^\/api\/orders\/(.+)$/);
    if (m) { const o = orders[decodeURIComponent(m[1])]; return o ? j(200, o) : j(404, { error: 'nf' }); }
    j(404, {});
  });
}
// сломанный: у товаров нет price (тип), и IDOR (любой токен → 200)
function brokenProvider() {
  return http.createServer((req, res) => {
    const j = (c, o) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
    if (req.url === '/api/health') return j(200, { ok: true });
    if (req.url === '/api/products') return j(200, [{ id: 1, name: 'Роза' }]); // нет price
    if (req.method === 'POST' && req.url === '/api/orders') return j(201, { order_number: 'ORD-x', total: 3.0 });
    if (req.url.startsWith('/api/orders/')) return j(200, { order_number: 'whatever', total: 1 }); // IDOR
    j(404, {});
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const codegen = require('../codegen.js');
  const verifier = require('../verify.js');

  console.log('codegen:');
  const cjs = codegen.generate('js').code;
  check('JS-клиент: класс и async-методы', /class FlowerShopClient/.test(cjs) && /async createOrder\(input\)/.test(cjs) && /async getOrder\(orderNumber\)/.test(cjs));
  const cpy = codegen.generate('python').code;
  check('Python-клиент: snake_case методы', /class FlowerShopClient/.test(cpy) && /def create_order\(self, order_input\)/.test(cpy) && /def list_products\(self\)/.test(cpy));
  const cts = codegen.generate('ts-types').code;
  check('TS-типы: интерфейсы из спецификации', /export interface Product/.test(cts) && /price: number;/.test(cts) && /order_number: string;/.test(cts));
  check('неизвестный язык → ошибка', !!codegen.generate('cobol').error);
  // сгенерированный JS-клиент реально исполняется
  const Client = eval('(function(){const module={exports:{}};' + cjs + ';return module.exports;})()');
  check('сгенерированный клиент инстанцируется', typeof new Client('http://x').listProducts === 'function');

  console.log('CDC — исправный провайдер:');
  const good = goodProvider(); const gp = await listen(good);
  const rGood = await verifier.verify(`http://localhost:${gp}`);
  check('пакт удовлетворён полностью', rGood.ok === true && rGood.passed === rGood.total && rGood.total === 5);
  check('типовой матчер: order_number (строка-токен) прошёл', rGood.results.find((r) => r.id === 'get-order').ok);
  check('приватность: неизвестный токен → 404 прошёл', rGood.results.find((r) => r.id === 'order-privacy').ok);

  console.log('CDC — сломанный провайдер:');
  const broken = brokenProvider(); const bp = await listen(broken);
  const rBad = await verifier.verify(`http://localhost:${bp}`);
  check('пакт НЕ удовлетворён', rBad.ok === false && rBad.passed < rBad.total);
  const prod = rBad.results.find((r) => r.id === 'products');
  check('products: пойман отсутствующий price', !prod.ok && prod.mismatches.some((m) => /price/.test(m.path)));
  check('order-privacy: IDOR пойман (ждали 404, получили 200)', !rBad.results.find((r) => r.id === 'order-privacy').ok);

  console.log('HTTP:');
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const spec = await (await fetch(base + '/api/spec')).json();
  check('spec отдаётся', Array.isArray(spec.operations) && spec.operations.length >= 4);
  const gen = await (await fetch(base + '/api/codegen?lang=python')).text();
  check('codegen через HTTP', /def create_order/.test(gen));
  const v = await (await fetch(base + '/api/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: `http://localhost:${gp}` }) })).json();
  check('verify через HTTP: исправный ok', v.ok === true);
  const q = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"результат верификации"}' })).json();
  check('ask (rules) про пакт', /пакт|взаимозамен/i.test(q.reply) && q.engine === 'rules');

  srv.close(); good.close(); broken.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
