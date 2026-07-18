// test/smoke.mjs — проверка авто-эвалов (детерминированный движок).
// Контрактный набор против исправного и сломанного бэкендов, регрессии, поведение.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

// --- исправный бэкенд контракта ---
function goodBackend() {
  const products = [{ id: 1, name: 'Роза', price: 1.5 }, { id: 2, name: 'Тюльпан', price: 0.8 }];
  const orders = {}; let seq = 1000;
  return http.createServer((req, res) => {
    const j = (c, o) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
    if (req.url === '/api/products') return j(200, products);
    if (req.method === 'POST' && req.url === '/api/orders') {
      let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => {
        const p = JSON.parse(b || '{}');
        if (!Array.isArray(p.items) || !p.items.length) return j(400, { error: 'items required' });
        const total = p.items.reduce((s, it) => { const pr = products.find((x) => x.id === it.product_id); return s + (pr ? pr.price * it.quantity : 0); }, 0);
        const token = 'ORD-' + ++seq; orders[token] = { order_number: token, total: Math.round(total * 100) / 100, items: p.items };
        j(201, orders[token]);
      }); return;
    }
    const m = req.url.match(/^\/api\/orders\/(.+)$/);
    if (m) { const o = orders[decodeURIComponent(m[1])]; return o ? j(200, o) : j(404, { error: 'not found' }); }
    j(404, {});
  });
}

// --- сломанный бэкенд: нет price, неверный total, IDOR, принимает пустой заказ ---
function brokenBackend() {
  return http.createServer((req, res) => {
    const j = (c, o) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
    if (req.url === '/api/products') return j(200, [{ id: 1, name: 'Роза' }]); // нет price
    if (req.method === 'POST' && req.url === '/api/orders') { let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => j(200, { order_number: 'ORD-x', total: 999 })); return; }
    const m = req.url.match(/^\/api\/orders\/(.+)$/);
    if (m) return j(200, { order_number: decodeURIComponent(m[1]), total: 999 }); // IDOR: любой токен
    j(404, {});
  });
}

// --- mock-витрина с сессиями ---
function chatBackend() {
  const sess = {};
  return http.createServer((req, res) => {
    if (req.method === 'POST' && req.url === '/api/chat') {
      let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => {
        const { sessionId, message } = JSON.parse(b || '{}'); const s = sess[sessionId] || (sess[sessionId] = {});
        let reply;
        if (/каталог|покажи/i.test(message)) reply = 'Вот каталог: Роза, Тюльпан, Пион.';
        else if (/добав/i.test(message)) reply = 'Добавил в корзину.';
        else if (/оформ/i.test(message)) { s.await = true; reply = 'На какое имя оформить?'; }
        else if (s.await) { s.await = false; reply = 'Готово! Заказ оформлен, номер ORD-1001.'; }
        else reply = 'Чем помочь?';
        res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ reply }));
      }); return;
    }
    res.writeHead(404); res.end('{}');
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const runner = require('../runner.js');
  const scorecard = require('../scorecard.js');
  const good = goodBackend(), broken = brokenBackend(), chat = chatBackend();
  const [gp, bp, cp] = await Promise.all([listen(good), listen(broken), listen(chat)]);
  const at = () => 't';

  console.log('контрактный набор — исправный бэкенд:');
  const cGood = await runner.runContract(`http://localhost:${gp}`, at);
  check('исправный: балл 100', cGood.score === 100 && cGood.passed === cGood.total);
  check('инвариант total пройден', cGood.results.find((r) => r.id === 'order-total-invariant').pass);
  check('приватность токена пройдена', cGood.results.find((r) => r.id === 'order-privacy').pass);

  console.log('контрактный набор — сломанный бэкенд:');
  const cBad = await runner.runContract(`http://localhost:${bp}`, at);
  const failed = new Set(cBad.results.filter((r) => !r.pass).map((r) => r.id));
  check('форма products провалена (нет price)', failed.has('products-shape'));
  check('инвариант total провален (неверная сумма)', failed.has('order-total-invariant'));
  check('IDOR пойман (privacy провален)', failed.has('order-privacy'));
  check('пустой заказ не отклонён (validation провален)', failed.has('order-validation'));
  check('балл сломанного заметно ниже', cBad.score < cGood.score);

  console.log('регрессии против baseline:');
  scorecard.record(cGood); scorecard.setBaseline(cGood);
  const cmp = scorecard.compare(cBad, scorecard.getBaseline());
  check('baseline задан', cmp.hasBaseline);
  check('регрессии обнаружены', cmp.regressions.length >= 3 && cmp.regressions.some((r) => r.id === 'order-privacy'));
  check('Δбалл отрицательная', cmp.scoreDelta < 0);

  console.log('поведенческий набор — витрина:');
  const beh = await runner.runBehavior(`http://localhost:${cp}`, at);
  check('витрина: все поведенческие кейсы пройдены', beh.score === 100 && beh.passed === beh.total);

  console.log('HTTP:');
  process.env.TARGET_URL = `http://localhost:${gp}`;
  process.env.CHAT_URL = `http://localhost:${cp}`;
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const post = async (p, b) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })).json();

  const h = await (await fetch(base + '/api/health')).json();
  check('движок rules', h.engine === 'rules');
  const run = await post('/api/run', {});
  check('HTTP /api/run: балл 100', run.score === 100);
  const bl = await post('/api/baseline', {});
  check('HTTP baseline сохранён', bl.ok === true);
  const behRun = await post('/api/run-behavior', {});
  check('HTTP /api/run-behavior пройден', behRun.score === 100);
  const q = await post('/api/ask', { message: 'какой балл?' });
  check('HTTP ask (rules)', /балл/i.test(q.reply) && q.engine === 'rules');

  srv.close(); good.close(); broken.close(); chat.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
