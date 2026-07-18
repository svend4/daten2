// smoke.mjs — реальные HTTP-проверки кросс-языкового верификатора.
// Поднимаем 4 mock-порта одного контракта: 3 эквивалентных (как разные языки с
// одинаковым поведением) + 1 расходящийся (цена товара#1 завышена и статус заказа
// другой — типичный «дрейф одного порта»). Проверяем: эквивалентные признаны
// одинаковыми, расходящийся пойман с точным путём, baseline-waiver ловит только
// новое, всё это по HTTP через server.js, детерминированно.
import http from 'node:http';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const runner = require('../runner');
const app = require('../server');

let passed = 0;
const ok = (c, m) => { assert.ok(c, m); console.log('  ✓', m); passed++; };

// Каноническая витрина (одинакова у эквивалентных портов). Порт-«диверджент»
// переопределяет цену розы и статус заказа.
function makePort({ rosePrice = 200, orderStatus = 'pending' } = {}) {
  const catalog = [
    { id: 1, name: 'Роза', price: rosePrice, active: true, image: '/img/rose.jpg' },
    { id: 2, name: 'Тюльпан', price: 90, active: true, image: '/img/tulip.jpg' },
    { id: 3, name: 'Пион', price: 300, active: true, image: '/img/peony.jpg' },
  ];
  const orders = new Map();
  let seq = 1000;
  const priceOf = (id) => catalog.find((p) => p.id === id).price;
  const nameOf = (id) => catalog.find((p) => p.id === id).name;
  return http.createServer((req, res) => {
    const send = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)); };
    const url = req.url;
    if (req.method === 'GET' && url === '/api/health') return send(200, { status: 'ok', level: 'mock-' + rosePrice });
    if (req.method === 'GET' && url === '/api/products') return send(200, { products: catalog });
    if (req.method === 'POST' && url === '/api/orders') {
      let body = ''; req.on('data', (c) => (body += c)); req.on('end', () => {
        let items = []; try { items = JSON.parse(body).items || []; } catch { /* ignore */ }
        const line = items.map((it) => ({ name: nameOf(it.product_id), quantity: it.quantity, price: priceOf(it.product_id) }));
        const total = line.reduce((s, l) => s + l.price * l.quantity, 0);
        const on = 'ORD-' + (++seq);
        orders.set(on, { order_number: on, status: orderStatus, items: line, total, created_at: '2020-01-01T00:00:00Z' });
        send(201, { order_number: on, total, status: orderStatus });
      });
      return;
    }
    const m = url.match(/^\/api\/orders\/(.+)$/);
    if (req.method === 'GET' && m) { const o = orders.get(decodeURIComponent(m[1])); return o ? send(200, o) : send(404, { error: 'not found' }); }
    send(404, {});
  });
}

const listen = (srv) => new Promise((r) => srv.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${srv.address().port}`)));
const post = (base, path, body) => new Promise((resolve, reject) => {
  const data = JSON.stringify(body || {});
  const u = new URL(base + path);
  const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
    (res) => { let b = ''; res.on('data', (c) => (b += c)); res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(b) }); } catch (e) { reject(e); } }); });
  req.on('error', reject); req.end(data);
});

async function main() {
  const a = makePort(), b = makePort(), c = makePort();                 // три эквивалентных «языка»
  const bad = makePort({ rosePrice: 250, orderStatus: 'created' });     // расходящийся порт
  const [ua, ub, uc, ubad] = await Promise.all([listen(a), listen(b), listen(c), listen(bad)]);
  const eq = [{ name: 'php', url: ua }, { name: 'flask', url: ub }, { name: 'express', url: uc }];
  const withBad = [...eq, { name: 'django-divergent', url: ubad }];

  console.log('Эквивалентные порты признаются одинаковыми:');
  const runEq = await runner.runAll(eq, { referenceName: 'php' });
  ok(runEq.allEquivalent, `все ${runEq.backends.length} портов эквивалентны эталону «${runEq.reference}»`);
  ok(runEq.divergences.length === 0, 'ни одного расхождения между идентичными портами');
  ok(runEq.steps.length === 4, 'сверены все 4 шага контракта (health/products/create/get)');

  console.log('Расходящийся порт пойман:');
  const runBad = await runner.runAll(withBad, { referenceName: 'php' });
  ok(!runBad.allEquivalent, 'полная эквивалентность нарушена');
  const dv = runBad.divergences.filter((d) => d.backend === 'django-divergent');
  ok(dv.length > 0, `расхождения приписаны именно расходящемуся порту (${dv.length})`);
  ok(dv.some((d) => d.step === 'products' && /price/.test(d.path) && d.reference === 200 && d.actual === 250), 'пойман завышенный прайс розы (products.price 200≠250)');
  ok(dv.some((d) => d.step === 'get-order' && d.path === 'status' && d.reference === 'pending' && d.actual === 'created'), 'пойман иной статус заказа (pending≠created)');
  ok(dv.some((d) => d.step === 'get-order' && /total/.test(d.path)), 'завышенная цена каскадом изменила сумму заказа');
  ok(runBad.byBackend.express.equivalent && runBad.byBackend.flask.equivalent, 'корректные порты остаются помеченными эквивалентными');

  console.log('Baseline-waiver ловит только новое:');
  const cmpAccepted = runner.compare(runBad, runBad);
  ok(cmpAccepted.newDivergences.length === 0, 'если все расхождения приняты как baseline — новых нет');
  const cmpFresh = runner.compare(runBad, runEq);
  ok(cmpFresh.newDivergences.length === dv.length, 'против чистого baseline все расхождения — новые');

  console.log('Детерминизм:');
  const again = await runner.runAll(withBad, { referenceName: 'php' });
  ok(JSON.stringify(again.divergences) === JSON.stringify(runBad.divergences), 'повторный прогон даёт те же расхождения');

  console.log('HTTP через server.js:');
  const api = await new Promise((r) => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  const apiBase = `http://127.0.0.1:${api.address().port}`;
  const vEq = await post(apiBase, '/api/verify', { backends: eq, referenceName: 'php' });
  ok(vEq.status === 200 && vEq.body.allEquivalent, 'POST /api/verify на эквивалентных → allEquivalent');
  const vBad = await post(apiBase, '/api/verify', { backends: withBad, referenceName: 'php' });
  ok(vBad.status === 200 && !vBad.body.allEquivalent && vBad.body.divergences.length > 0, 'POST /api/verify ловит расходящийся порт');
  const baseResp = await post(apiBase, '/api/baseline', {});
  ok(baseResp.status === 200 && baseResp.body.accepted === vBad.body.divergences.length, 'POST /api/baseline фиксирует расхождения как принятые');
  const vBad2 = await post(apiBase, '/api/verify', { backends: withBad, referenceName: 'php' });
  ok(vBad2.body.compare.hasBaseline && vBad2.body.compare.newDivergences.length === 0, 'после waiver повторная сверка не показывает новых расхождений');
  const askResp = await post(apiBase, '/api/ask', { message: 'какие порты расходятся?' });
  ok(askResp.status === 200 && /django-divergent|расход/i.test(askResp.body.reply), '/api/ask называет расходящийся порт словами');

  [a, b, c, bad, api].forEach((s) => s.close());
  console.log(`\nВсе проверки пройдены (${passed}).`);
}

main().catch((e) => { console.error('ПРОВАЛ:', e); process.exit(1); });
