// test/smoke.mjs — проверка property-based харнесса.
// Свойства держатся на исправном провайдере; на сломанных — конкретное свойство
// падает с минимальным (сжатым) контрпримером; детерминизм по seed.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;
const PRODUCTS = [{ id: 1, name: 'Роза', price: 1.5 }, { id: 2, name: 'Тюльпан', price: 0.8 }, { id: 3, name: 'Пион', price: 2.2 }];

// bug: 'none' | 'total' | 'idor' | 'flaky'
function provider(bug) {
  const orders = {}; let seq = 1000, nonce = 0;
  return http.createServer((req, res) => {
    const j = (c, o) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
    if (req.url === '/api/products') { const list = bug === 'flaky' ? PRODUCTS.map((p) => ({ ...p, _nonce: nonce++ })) : PRODUCTS; return j(200, list); }
    if (req.method === 'POST' && req.url === '/api/orders') {
      let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => {
        const p = JSON.parse(b || '{}'); if (!p.items || !p.items.length) return j(400, { error: 'items' });
        const total = p.items.reduce((s, it) => { const pr = PRODUCTS.find((x) => x.id === it.product_id); return s + (pr ? pr.price * it.quantity : 0); }, 0);
        const t = 'ORD-' + ++seq; orders[t] = { order_number: t, total: bug === 'total' ? 999 : Math.round(total * 100) / 100, items: p.items };
        j(201, orders[t]);
      }); return;
    }
    const m = req.url.match(/^\/api\/orders\/(.+)$/);
    if (m) { const tok = decodeURIComponent(m[1]); if (bug === 'idor') return j(200, { order_number: tok, total: 1 }); const o = orders[tok]; return o ? j(200, o) : j(404, { error: 'nf' }); }
    j(404, {});
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const runner = require('../runner.js');
  const start = async (bug) => { const s = provider(bug); const p = await listen(s); return { s, url: `http://localhost:${p}` }; };

  console.log('исправный провайдер — все инварианты держатся:');
  const good = await start('none');
  const rGood = await runner.runAll(good.url, { iterations: 30, seed: 1 });
  check('все 5 свойств держатся', rGood.allHold && rGood.held === 5 && rGood.total === 5);
  check('каждое свойство прогнано на входах', rGood.results.every((r) => r.tested >= 1));

  console.log('нарушение total → свойство падает + сжатие контрпримера:');
  const badTotal = await start('total');
  const rTotal = await runner.runAll(badTotal.url, { iterations: 30, seed: 1 });
  const p1 = rTotal.results.find((r) => r.id === 'total-invariant');
  check('total-invariant нарушен', !p1.ok);
  check('контрпример сжат до минимума (1 позиция, кол-во 1)', p1.counterexample.items.length === 1 && p1.counterexample.items[0].quantity === 1);
  check('другие свойства держатся', rTotal.results.filter((r) => r.id !== 'total-invariant').every((r) => r.ok));

  console.log('IDOR → приватность токена нарушена:');
  const idor = await start('idor');
  const rIdor = await runner.runAll(idor.url, { iterations: 20, seed: 1 });
  const p3 = rIdor.results.find((r) => r.id === 'token-privacy');
  check('token-privacy нарушен (IDOR пойман)', !p3.ok && /утечка/.test(p3.detail));

  console.log('неидемпотентный каталог → свойство падает:');
  const flaky = await start('flaky');
  const rFlaky = await runner.runAll(flaky.url, { iterations: 10, seed: 1 });
  check('read-idempotent нарушен', !rFlaky.results.find((r) => r.id === 'read-idempotent').ok);

  console.log('детерминизм:');
  const r1 = await runner.runAll(badTotal.url, { iterations: 30, seed: 7 });
  const r2 = await runner.runAll(badTotal.url, { iterations: 30, seed: 7 });
  const c1 = r1.results.find((r) => r.id === 'total-invariant').counterexample;
  const c2 = r2.results.find((r) => r.id === 'total-invariant').counterexample;
  check('тот же seed → тот же контрпример', JSON.stringify(c1) === JSON.stringify(c2));

  console.log('HTTP:');
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const props = await (await fetch(base + '/api/properties')).json();
  check('/api/properties список', props.properties.length === 5);
  const runHttp = await (await fetch(base + '/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: good.url, iterations: 15 }) })).json();
  check('/api/run: исправный → allHold', runHttp.allHold === true);
  const q = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"инварианты держатся?"}' })).json();
  check('ask (rules) про инварианты', /инвариант|свойств/i.test(q.reply) && q.engine === 'rules');

  srv.close(); good.s.close(); badTotal.s.close(); idor.s.close(); flaky.s.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
