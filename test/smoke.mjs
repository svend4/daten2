// test/smoke.mjs — проверка слоя наблюдаемости на живых mock-стеках.
// Четыре стека: fast, slow, flaky (половина 500), offline (порт закрыт).
// Проверяем корректность бенчмарка (p95, throughput, success), рейтинг, /metrics
// и детерминированную интерпретацию.
import http from 'node:http';

delete process.env.ANTHROPIC_API_KEY; // детерминированный аналитик

const PRODUCTS = [{ id: 1, name: 'Роза', price: 1.5 }];
function makeLevel({ delay = 0, flaky = false }) {
  let n = 0;
  return http.createServer((req, res) => {
    const respond = () => {
      if (req.url === '/api/health') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end('{"ok":true}'); }
      if (flaky && (n++ % 2 === 0)) { res.writeHead(500, { 'Content-Type': 'application/json' }); return res.end('{"error":"boom"}'); }
      res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(PRODUCTS));
    };
    if (delay) setTimeout(respond, delay); else respond();
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const fast = makeLevel({ delay: 3 });
  const slow = makeLevel({ delay: 60 });
  const flaky = makeLevel({ delay: 3, flaky: true });
  const [pf, ps, pk] = await Promise.all([listen(fast), listen(slow), listen(flaky)]);

  process.env.OBS_LEVELS = JSON.stringify([
    { id: 'fast',    name: 'Fast',    url: `http://localhost:${pf}` },
    { id: 'slow',    name: 'Slow',    url: `http://localhost:${ps}` },
    { id: 'flaky',   name: 'Flaky',   url: `http://localhost:${pk}` },
    { id: 'offline', name: 'Offline', url: 'http://localhost:1' },
  ]);

  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const get = async (p) => (await fetch(base + p)).json();
  const getText = async (p) => (await fetch(base + p)).text();

  const h = await get('/api/health');
  check('движок rule-based', h.engine === 'rules');
  check('видит 4 стека', h.levels === 4);

  console.log('бенчмарк:');
  const r = await (await fetch(base + '/api/bench', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: '/api/products', requests: 30, concurrency: 5 }) })).json();
  const by = (id) => r.results.find((x) => x.id === id);
  const F = by('fast'), S = by('slow'), K = by('flaky'), O = by('offline');

  check('fast: p95 измерен', F.alive && F.latency_ms.p95 != null);
  check('fast быстрее slow по p95', F.latency_ms.p95 < S.latency_ms.p95);
  check('fast throughput выше slow', F.throughput_rps > S.throughput_rps);
  check('fast и slow success 100%', F.success_ratio === 1 && S.success_ratio === 1);
  check('flaky success < 100%', K.alive && K.success_ratio < 1);
  check('offline помечен alive=false', O.alive === false);
  check('рейтинг: fast — первый', r.ranked[0] === 'fast');
  check('рейтинг: offline — последний', r.ranked[r.ranked.length - 1] === 'offline');

  console.log('метрики Prometheus:');
  const m = await getText('/metrics');
  check('есть latency p95 fast', m.includes('flowershop_bench_latency_ms{level="fast",stack="Fast",quantile="p95"}'));
  check('есть throughput', /flowershop_bench_throughput_rps\{level="fast"/.test(m));
  check('есть success_ratio flaky < 1', /flowershop_bench_success_ratio\{level="flaky"[^}]*\} 0\.\d+/.test(m));
  check('offline up=0', m.includes('flowershop_bench_up{level="offline",stack="Offline"} 0'));
  check('HELP/TYPE присутствуют', m.includes('# TYPE flowershop_bench_latency_ms gauge'));

  console.log('интерпретация (движок rules):');
  const q1 = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'какой стек самый быстрый?' }) })).json();
  check('самый быстрый: назван Fast', /Fast/.test(q1.reply) && q1.engine === 'rules');
  const q2 = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'есть проблемные стеки?' }) })).json();
  check('проблемы: упомянуты flaky/offline', /Flaky|Offline/.test(q2.reply));
  const q3 = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'сравни пропускную способность' }) })).json();
  check('throughput: перечислены rps', /rps/.test(q3.reply));

  srv.close(); fast.close(); slow.close(); flaky.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}

main().catch((e) => { console.error(e); process.exit(1); });
