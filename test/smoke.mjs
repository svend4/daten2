// test/smoke.mjs — проверка самооптимизирующегося роутера.
// Три mock-уровня: A (быстрый, дешёвый), B (медленный, дешёвый), C (быстрый, дорогой).
// Проверяем: (1) после разогрева трафик сходится к лучшему (A);
// (2) при деградации A роутер уводит трафик (на B) и продолжает отвечать (failover).
import http from 'node:http';

delete process.env.ANTHROPIC_API_KEY; // детерминированный движок объяснений

// --- управляемые mock-уровни ------------------------------------------------
function makeBackend(cfg) {
  return http.createServer((req, res) => {
    if (req.url === '/api/health') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end('{"ok":true}'); }
    if (req.url.startsWith('/api/products')) {
      setTimeout(() => {
        if (cfg.fail) { res.writeHead(500, { 'Content-Type': 'application/json' }); res.end('{"error":"down"}'); }
        else { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify([{ id: 1, name: 'Роза', price: 1.5 }])); }
      }, cfg.delay);
      return;
    }
    res.writeHead(404); res.end('{}');
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

const cfgA = { delay: 10, fail: false };
const cfgB = { delay: 120, fail: false };
const cfgC = { delay: 10, fail: false };

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const A = makeBackend(cfgA), B = makeBackend(cfgB), C = makeBackend(cfgC);
  const [pa, pb, pc] = await Promise.all([listen(A), listen(B), listen(C)]);
  process.env.ROUTER_BACKENDS = JSON.stringify([
    { id: 'A', name: 'A быстрый-дешёвый', url: `http://localhost:${pa}`, cost: 1 },
    { id: 'B', name: 'B медленный',       url: `http://localhost:${pb}`, cost: 1 },
    { id: 'C', name: 'C дорогой',         url: `http://localhost:${pc}`, cost: 3 },
  ]);

  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;

  await fetch(base + '/api/router/refresh', { method: 'POST' });
  const stats0 = await (await fetch(base + '/api/router/stats')).json();
  check('движок rule-based', (await (await fetch(base + '/api/health')).json()).engine === 'rules');
  check('3 уровня online', stats0.levels.filter((l) => l.alive).length === 3);

  // сбор трафика по X-Served-By
  async function fire(n) {
    const counts = {}; let ok = 0;
    for (let i = 0; i < n; i++) {
      const r = await fetch(base + '/api/products');
      if (r.status === 200) ok++;
      const by = r.headers.get('x-served-by-level') || '?';
      counts[by] = (counts[by] || 0) + 1;
    }
    return { counts, ok };
  }

  console.log('разогрев + сходимость к лучшему уровню:');
  await fire(12); // разогрев модели
  const good = await fire(40);
  console.log('    распределение (норма):', JSON.stringify(good.counts));
  check('A обслуживает большинство', (good.counts.A || 0) > (good.counts.B || 0) && (good.counts.A || 0) > (good.counts.C || 0));
  check('доля A ≥ 50%', (good.counts.A || 0) >= 20);
  const dec1 = await (await fetch(base + '/api/router/decide')).json();
  check('решение роутера — A', dec1.choice === 'A');

  console.log('деградация A → уход трафика и failover:');
  cfgA.fail = true; cfgA.delay = 200; // A начал падать и тормозить
  const bad = await fire(40);
  console.log('    распределение (деградация):', JSON.stringify(bad.counts));
  check('все запросы всё равно успешны (failover)', bad.ok === 40);
  check('A почти не обслуживает', (bad.counts.A || 0) < (good.counts.A || 0) && (bad.counts.A || 0) <= 5);
  check('B принял большинство', (bad.counts.B || 0) > (bad.counts.C || 0));
  const dec2 = await (await fetch(base + '/api/router/decide')).json();
  check('решение роутера сменилось с A', dec2.choice !== 'A');
  const sA = (await (await fetch(base + '/api/router/stats')).json()).levels.find((l) => l.id === 'A');
  check('надёжность A упала < 60%', sA.success < 0.6);

  console.log('объяснение (движок rules):');
  const ex = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'сравни все уровни' }) })).json();
  check('объяснение перечисляет уровни', /A быстрый|B медленный|C дорогой/.test(ex.reply) && ex.engine === 'rules');

  srv.close(); A.close(); B.close(); C.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}

main().catch((e) => { console.error(e); process.exit(1); });
