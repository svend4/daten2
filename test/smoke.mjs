// test/smoke.mjs — проверка chaos-харнесса.
// Инъекция сбоев, failover держит SLO при частичном отказе, ломается при полном,
// живой устойчивый прокси, метрики нагрузки.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

function level(name) {
  return http.createServer((req, res) => {
    if (req.url.startsWith('/api/products')) { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify([{ id: 1, name: 'Роза', price: 1.5, level: name }])); }
    if (req.url === '/api/health') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end('{"ok":true}'); }
    res.writeHead(404); res.end('{}');
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const A = level('A'), B = level('B'), C = level('C');
  const [pa, pb, pc] = await Promise.all([listen(A), listen(B), listen(C)]);
  process.env.CHAOS_TARGETS = JSON.stringify([
    { id: 'A', name: 'A', url: `http://localhost:${pa}` },
    { id: 'B', name: 'B', url: `http://localhost:${pb}` },
    { id: 'C', name: 'C', url: `http://localhost:${pc}` },
  ]);

  const targetsMod = require('../targets.js');
  const resilient = require('../resilient.js');
  const runner = require('../runner.js');

  console.log('инъекция сбоев и failover:');
  targetsMod.setFault('A', { down: true });
  let r = await resilient.request(targetsMod.targets, { path: '/api/products' });
  check('уровень A упал → обслужил B (failover)', r.ok && r.servedBy === 'B' && r.failover === true);
  targetsMod.setFault('A', { down: false }); targetsMod.setFault('A', { errorRate: 1.0 });
  r = await resilient.request(targetsMod.targets, { path: '/api/products' });
  check('A сыпет ошибками → failover на B', r.ok && r.servedBy === 'B');
  targetsMod.clearFaults();
  r = await resilient.request(targetsMod.targets, { path: '/api/products' });
  check('без сбоев обслуживает primary (A)', r.ok && r.servedBy === 'A' && r.failover === false);

  console.log('chaos-эксперименты (гипотезы SLO):');
  const rep = await runner.runAll({ requests: 30, concurrency: 6 });
  const by = (id) => rep.results.find((x) => x.id === id);
  check('steady-state: SLO держится', by('steady-state').held && by('steady-state').pass);
  check('one-level-down: SLO держится через failover', by('one-level-down').held === true && by('one-level-down').pass);
  check('level-errors: failover маскирует 500', by('level-errors').held === true && by('level-errors').pass);
  check('all-down: SLO нарушен (ожидаемо)', by('all-down').held === false && by('all-down').pass);
  check('весь прогон «как ожидалось»', rep.allPass && rep.passed === rep.total);
  check('после экспериментов сбои сняты', targetsMod.targets.every((t) => !t.fault.down && t.fault.errorRate === 0));

  console.log('HTTP:');
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const post = async (p, b) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })).json();

  const h = await (await fetch(base + '/api/health')).json();
  check('движок rules, 3 цели', h.engine === 'rules' && h.targets === 3);
  await post('/api/faults/A', { down: true });
  const prod = await fetch(base + '/api/products');
  check('живой прокси: A down → served by B, failover', prod.status === 200 && prod.headers.get('x-served-by') === 'B' && prod.headers.get('x-failover') === 'true');
  await post('/api/faults/clear');
  const runHttp = await post('/api/run', { requests: 24, concurrency: 6 });
  check('HTTP /api/run: все эксперименты как ожидалось', runHttp.allPass === true);
  const lt = await post('/api/loadtest', { requests: 20 });
  check('loadtest: метрики успеха и p95', lt.successRate === 1 && lt.p95 != null);
  const q = await post('/api/ask', { message: 'что с устойчивостью?' });
  check('ask (rules)', /chaos|устойчив|прогон/i.test(q.reply) && q.engine === 'rules');

  srv.close(); A.close(); B.close(); C.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
