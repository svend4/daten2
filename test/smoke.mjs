// test/smoke.mjs — проверка полиглот-бенчмарка.
// Живой прогон по mock-стекам (рейтинг по p95), детерминированная генерация отчёта, HTTP.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

function stack(delay) {
  return http.createServer((req, res) => {
    const respond = () => {
      if (req.url === '/api/health') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end('{"ok":true}'); }
      if (req.url.startsWith('/api/products')) { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end('[{"id":1,"name":"Роза","price":1.5}]'); }
      res.writeHead(404); res.end('{}');
    };
    if (delay) setTimeout(respond, delay); else respond();
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const runner = require('../runner.js');
  const report = require('../report.js');

  const fast = stack(3), slow = stack(60), off = stack(0);
  const [pf, ps] = await Promise.all([listen(fast), listen(slow)]);
  off.close(); // сразу «offline»

  const stacks = [
    { id: 'fast', name: 'Fast', language: 'X', storage: 'mem', watts: 10, url: `http://localhost:${pf}` },
    { id: 'slow', name: 'Slow', language: 'Y', storage: 'mem', watts: 20, url: `http://localhost:${ps}` },
    { id: 'down', name: 'Down', language: 'Z', storage: 'mem', watts: 30, url: 'http://localhost:1' },
  ];

  console.log('прогон + рейтинг:');
  const results = await runner.runAll(stacks, { requests: 20, concurrency: 4, warmup: 2 });
  const byId = Object.fromEntries(results.map((r) => [r.id, r]));
  check('fast быстрее slow по p95', byId.fast.p95 < byId.slow.p95);
  check('fast — ранг 1', byId.fast.rank === 1);
  check('down помечен offline и без ранга', byId.down.alive === false && byId.down.rank === null);
  check('посчитан rps/Вт', byId.fast.rps_per_watt != null && byId.fast.rps_per_watt > 0);

  console.log('генерация отчёта (детерминированная):');
  const fixed = [
    { id: 'a', name: 'L1 · PHP', language: 'PHP', storage: 'SQLite', watts: 12, alive: true, rank: 1, p50: 5, p95: 8, p99: 10, rps: 900, success_ratio: 1, rps_per_watt: 75 },
    { id: 'b', name: 'L6 · Next.js', language: 'TS', storage: 'PostgreSQL', watts: 30, alive: true, rank: 2, p50: 20, p95: 40, p99: 55, rps: 300, success_ratio: 1, rps_per_watt: 10 },
    { id: 'c', name: 'L7 · Micro', language: 'Node+Py', storage: 'PostgreSQL', watts: 45, alive: false, rank: null },
  ];
  const meta = { endpoint: '/api/products', requests: 200, concurrency: 20, warmup: 5, at: '2026-01-01T00:00:00Z' };
  const md1 = report.markdown(fixed, meta);
  const md2 = report.markdown(fixed, meta);
  check('отчёт детерминирован (та же входная → та же строка)', md1 === md2);
  check('есть методология и воспроизводимость', /## Методология/.test(md1) && /## Воспроизводимость/.test(md1));
  check('таблица результатов со стеками', /L1 · PHP/.test(md1) && /L6 · Next.js/.test(md1));
  check('вывод: самый быстрый (p95) — первый', /Самый быстрый.*L1 · PHP/.test(md1));
  check('вывод: самый эффективный по rps/Вт', /Самый эффективный.*L1 · PHP/.test(md1));
  check('offline-стек отмечен', /L7 · Micro.*offline/.test(md1));
  const htmlOut = report.html(fixed, meta);
  check('HTML-отчёт самодостаточен (без внешних ссылок)', /<!doctype html>/.test(htmlOut) && !/https?:\/\/[^"']*\.(js|css)/.test(htmlOut));

  console.log('HTTP:');
  process.env.BENCH_STACKS = JSON.stringify(stacks);
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const st = await (await fetch(base + '/api/stacks')).json();
  check('/api/stacks с метаданными', st.stacks.length === 3 && st.stacks[0].language);
  const run = await (await fetch(base + '/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requests: 15, concurrency: 3 }) })).json();
  check('/api/run: есть результаты и meta', Array.isArray(run.results) && run.meta.requests === 15);
  const mdResp = await fetch(base + '/api/report.md');
  const mdText = await mdResp.text();
  check('/api/report.md отдаёт markdown', /text\/markdown/.test(mdResp.headers.get('content-type') || '') && /# Полиглот-бенчмарк/.test(mdText));
  const q = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"самый быстрый?"}' })).json();
  check('ask (rules) про самый быстрый', /быстр/i.test(q.reply) && q.engine === 'rules');

  srv.close(); fast.close(); slow.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
