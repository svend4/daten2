// test/smoke.mjs — проверка shadow/canary.
// Diff-тестирование (совпадение/расхождение/игнор изменчивых полей/ошибка кандидата),
// клиент всегда получает primary, канареечный сплит и авто-откат.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

// backend с настраиваемым поведением
function backend(opts) {
  let seq = 0;
  return http.createServer((req, res) => {
    const j = (c, o) => { res.writeHead(c, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
    if (req.url === '/api/products') {
      if (opts.fail) return j(500, { error: 'boom' });
      return j(200, [{ id: 1, name: 'Роза', price: opts.price ?? 1.5 }]);
    }
    if (req.method === 'POST' && req.url === '/api/orders') { seq++; return j(201, { order_number: (opts.tag || 'P') + '-' + seq, total: 3.0 }); }
    j(404, {});
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const primary = backend({ price: 1.5, tag: 'PRIM' });
  const same = backend({ price: 1.5, tag: 'CAND' });      // идентичный (кроме токена заказа)
  const diff = backend({ price: 9.9, tag: 'CAND' });      // расходится по цене
  const broken = backend({ fail: true, tag: 'CAND' });    // падает
  const [pp, sp, dp, bp] = await Promise.all([listen(primary), listen(same), listen(diff), listen(broken)]);

  process.env.PRIMARY_URL = `http://localhost:${pp}`;
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const cfg = (b) => fetch(base + '/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  const reset = () => fetch(base + '/api/reset', { method: 'POST' });
  const getStats = async () => (await fetch(base + '/api/stats')).json();

  console.log('shadow — идентичный кандидат:');
  await cfg({ primary: `http://localhost:${pp}`, candidate: `http://localhost:${sp}`, mode: 'shadow' }); await reset();
  let served;
  for (let i = 0; i < 5; i++) { const r = await fetch(base + '/api/products'); served = r.headers.get('x-served-by'); }
  let s = await getStats();
  check('клиента обслуживает primary', served === 'primary');
  check('shadow: все совпали (matchRate 1)', s.shadow.compared === 5 && s.shadow.matches === 5 && s.shadow.matchRate === 1);

  console.log('shadow — расходящийся кандидат:');
  await cfg({ candidate: `http://localhost:${dp}`, mode: 'shadow' }); await reset();
  for (let i = 0; i < 4; i++) await fetch(base + '/api/products');
  s = await getStats();
  check('расхождения обнаружены', s.shadow.diffs === 4 && s.shadow.matches === 0);
  check('diff указывает на цену', s.shadow.samples[0].diffs.some((d) => /price/.test(d.path)));

  console.log('shadow — игнор изменчивых полей (order_number):');
  await cfg({ candidate: `http://localhost:${sp}`, mode: 'shadow' }); await reset();
  for (let i = 0; i < 3; i++) await fetch(base + '/api/orders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"name":"x","items":[{"product_id":1,"quantity":2}]}' });
  s = await getStats();
  check('разные order_number НЕ считаются расхождением', s.shadow.matches === 3 && s.shadow.diffs === 0);

  console.log('shadow — кандидат падает:');
  await cfg({ candidate: `http://localhost:${bp}`, mode: 'shadow' }); await reset();
  for (let i = 0; i < 3; i++) { const r = await fetch(base + '/api/products'); if (r.status !== 200) failures++; }
  s = await getStats();
  check('ошибки кандидата учтены, клиент не пострадал', s.shadow.candidateErrors === 3);

  console.log('canary — сплит трафика:');
  await cfg({ candidate: `http://localhost:${sp}`, mode: 'canary', canaryPct: 0.5 }); await reset();
  const sides = {};
  for (let i = 0; i < 10; i++) { const r = await fetch(base + '/api/products'); const by = r.headers.get('x-served-by'); sides[by] = (sides[by] || 0) + 1; }
  check('~50% ушло на кандидат', sides.candidate === 5 && sides.primary === 5);

  console.log('canary — авто-откат при ошибках кандидата:');
  await cfg({ candidate: `http://localhost:${bp}`, mode: 'canary', canaryPct: 1.0 }); await reset();
  for (let i = 0; i < 8; i++) await fetch(base + '/api/products');
  const cfgNow = await (await fetch(base + '/api/config')).json();
  s = await getStats();
  check('произошёл авто-откат (pct→0, mode shadow)', cfgNow.canaryPct === 0 && cfgNow.mode === 'shadow' && s.canary.rollbacks >= 1);

  console.log('ask (rules):');
  const q = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"какие расхождения?"}' })).json();
  check('ask отвечает про shadow/diff', /shadow|сравн|расхожд/i.test(q.reply) && q.engine === 'rules');

  srv.close(); primary.close(); same.close(); diff.close(); broken.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
