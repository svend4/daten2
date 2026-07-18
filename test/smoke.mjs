// smoke.mjs — реальные HTTP-проверки маркетплейса бэкендов.
// Поднимаем mock-плагины: соответствующий контракту, ломающий его (заказ без
// order_number) и недоступный. Проверяем: гейт сертифицирует только настоящий
// бэкенд, каталог для роутера содержит лишь сертифицированные, semver выбирает
// новейшую версию, yank убирает из каталога, битый манифест отклоняется без пробы.
import http from 'node:http';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { createRegistry } = require('../registry');
const app = require('../server');

let passed = 0;
const ok = (c, m) => { assert.ok(c, m); console.log('  ✓', m); passed++; };

// mock-бэкенд контракта; broken=true → заказ без order_number
function backend({ broken = false } = {}) {
  const catalog = [{ id: 1, name: 'Роза', price: 200 }, { id: 2, name: 'Тюльпан', price: 90 }];
  const orders = new Map(); let seq = 5000;
  return http.createServer((req, res) => {
    const send = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)); };
    if (req.method === 'GET' && req.url === '/api/health') return send(200, { status: 'ok', level: broken ? 'broken' : 'mock' });
    if (req.method === 'GET' && req.url === '/api/products') return send(200, { products: catalog });
    if (req.method === 'POST' && req.url === '/api/orders') {
      let body = ''; req.on('data', (c) => (body += c)); req.on('end', () => {
        let items = []; try { items = JSON.parse(body).items || []; } catch { /* ignore */ }
        const total = items.reduce((s, it) => s + (catalog.find((p) => p.id === it.product_id)?.price || 0) * it.quantity, 0);
        if (broken) return send(201, { total }); // НЕТ order_number — нарушение контракта
        const on = 'ORD-' + (++seq); orders.set(on, { order_number: on, status: 'pending', total, items });
        send(201, { order_number: on, total, status: 'pending' });
      });
      return;
    }
    const m = req.url.match(/^\/api\/orders\/(.+)$/);
    if (req.method === 'GET' && m) { const o = orders.get(decodeURIComponent(m[1])); return o ? send(200, o) : send(404, { error: 'нет' }); }
    send(404, {});
  });
}
const listen = (s) => new Promise((r) => s.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${s.address().port}`)));
const post = (base, p, body) => new Promise((resolve, reject) => {
  const data = JSON.stringify(body || {}); const u = new URL(base + p);
  const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
    (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(d) }); } catch (e) { reject(e); } }); });
  req.on('error', reject); req.end(data);
});
const get = (base, p) => new Promise((resolve, reject) => { http.get(base + p, (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => resolve(JSON.parse(d))); }).on('error', reject); });

async function main() {
  const good = backend(); const brk = backend({ broken: true });
  const goodUrl = await listen(good); const brkUrl = await listen(brk);
  // недоступный: поднять и закрыть → connection refused
  const dead = backend(); const deadUrl = await listen(dead); await new Promise((r) => dead.close(r));

  console.log('Гейт соответствия контракту:');
  const reg = createRegistry();
  const rGood = await reg.publish({ id: 'acme-php', name: 'Acme PHP backend', version: '1.0.0', url: goodUrl, stack: 'PHP', cost: 0.001 });
  ok(rGood.state === 'certified' && rGood.score === 1, 'соответствующий бэкенд сертифицирован (score 1.0)');
  const rBrk = await reg.publish({ id: 'buggy-node', name: 'Buggy backend', version: '1.0.0', url: brkUrl, stack: 'Node' });
  ok(rBrk.state === 'rejected' && rBrk.reason === 'conformance' && rBrk.checks.find((c) => c.name === 'create-order').ok === false, 'бэкенд без order_number отклонён по соответствию');
  const rDead = await reg.publish({ id: 'ghost', name: 'Ghost backend', version: '1.0.0', url: deadUrl, stack: 'Rust' });
  ok(rDead.state === 'rejected' && rDead.checks[0].name === 'health' && !rDead.checks[0].ok, 'недоступный бэкенд отклонён (health провален)');

  console.log('Валидация манифеста (до живой пробы):');
  const rBadMan = await reg.publish({ id: 'Bad Id!', name: '', version: '1.x', url: 'not-a-url', stack: '' });
  ok(rBadMan.state === 'rejected' && rBadMan.reason === 'manifest' && rBadMan.errors.length >= 4, 'битый манифест отклонён без обращения к сети');

  console.log('Каталог для роутера — только сертифицированные:');
  const cat1 = reg.catalog();
  ok(cat1.length === 1 && cat1[0].id === 'acme-php' && cat1[0].url === goodUrl && cat1[0].version === '1.0.0', 'каталог содержит только сертифицированный acme-php в router-форме');

  console.log('Semver: новейшая сертифицированная версия побеждает:');
  await reg.publish({ id: 'acme-php', name: 'Acme PHP', version: '1.2.0', url: goodUrl, stack: 'PHP', cost: 0.001 });
  ok(reg.active('acme-php').version === '1.2.0' && reg.catalog()[0].version === '1.2.0', 'активна и в каталоге версия 1.2.0');
  await reg.publish({ id: 'acme-php', name: 'Acme PHP', version: '1.1.0', url: goodUrl, stack: 'PHP' });
  ok(reg.active('acme-php').version === '1.2.0', 'публикация более старой 1.1.0 не понижает активную');

  console.log('Yank убирает версию из каталога:');
  reg.yank('acme-php', '1.2.0');
  ok(reg.active('acme-php').version === '1.1.0', 'после yank 1.2.0 активной становится 1.1.0');
  reg.yank('acme-php', '1.1.0'); reg.yank('acme-php', '1.0.0');
  ok(reg.catalog().length === 0, 'после отзыва всех версий плагин исчезает из каталога');

  console.log('Детерминизм/идемпотентность:');
  const reg2 = createRegistry();
  const a = await reg2.publish({ id: 'acme-php', name: 'Acme', version: '1.0.0', url: goodUrl, stack: 'PHP' });
  const b = await reg2.publish({ id: 'acme-php', name: 'Acme', version: '1.0.0', url: goodUrl, stack: 'PHP' });
  ok(a.state === b.state && reg2.forId('acme-php').length === 1, 'повторная публикация той же версии не плодит записи');

  console.log('HTTP через server.js:');
  const api = await new Promise((r) => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  const apiBase = `http://127.0.0.1:${api.address().port}`;
  const pub = await post(apiBase, '/api/plugins', { id: 'shop-flask', name: 'Flask backend', version: '2.0.0', url: goodUrl, stack: 'Flask', regions: ['eu-north'] });
  ok(pub.status === 201 && pub.body.state === 'certified', 'POST /api/plugins сертифицирует соответствующий бэкенд');
  const pubBad = await post(apiBase, '/api/plugins', { id: 'flask-bug', name: 'Bug', version: '1.0.0', url: brkUrl, stack: 'Flask' });
  ok(pubBad.status === 400 && pubBad.body.state === 'rejected', 'POST /api/plugins отклоняет несоответствующий (400)');
  const cat = await get(apiBase, '/api/catalog');
  ok(cat.backends.length === 1 && cat.backends[0].id === 'shop-flask' && cat.backends[0].regions[0] === 'eu-north', 'GET /api/catalog отдаёт router-совместимый список сертифицированных');
  const ask = await post(apiBase, '/api/ask', { message: 'что в каталоге для роутера?' });
  ok(/shop-flask|каталог/i.test(ask.body.reply), '/api/ask описывает каталог словами');

  good.close(); brk.close(); api.close();
  console.log(`\nВсе проверки пройдены (${passed}).`);
}

main().catch((e) => { console.error('ПРОВАЛ:', e); process.exit(1); });
