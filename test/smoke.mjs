// test/smoke.mjs — проверка control-plane (портала).
// Опрос статусов, агрегация по категориям, обнаружение offline, HTTP.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

function svc(engine) {
  return http.createServer((req, res) => {
    if (req.url === '/api/health') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify({ ok: true, engine })); }
    res.writeHead(404); res.end('{}');
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const a = svc('rules'), b = svc('llm');
  const [pa, pb] = await Promise.all([listen(a), listen(b)]);
  // три сервиса в двух категориях: A(up,rules), B(up,llm), C(down — мёртвый порт)
  process.env.PORTAL_SERVICES = JSON.stringify([
    { id: 'a', name: 'Сервис A', cat: 'Маршрутизация', url: `http://localhost:${pa}`, dash: 'http://localhost:8080' },
    { id: 'b', name: 'Сервис B', cat: 'Качество', url: `http://localhost:${pb}`, dash: 'http://localhost:8090' },
    { id: 'c', name: 'Сервис C', cat: 'Качество', url: 'http://localhost:1', dash: 'http://localhost:8099' },
  ]);

  const registry = require('../registry.js');
  const monitor = require('../monitor.js');

  console.log('опрос статусов:');
  const snap = await monitor.pollAll(registry.services);
  check('всего 3 сервиса', snap.total === 3);
  check('2 онлайн, 1 offline', snap.up === 2 && snap.down === 1);
  check('движок распознан (rules/llm)', snap.services.find((s) => s.id === 'a').engine === 'rules' && snap.services.find((s) => s.id === 'b').engine === 'llm');
  check('C помечен offline', snap.services.find((s) => s.id === 'c').up === false);
  check('агрегация по категориям', snap.byCat['Маршрутизация'].up === 1 && snap.byCat['Качество'].up === 1 && snap.byCat['Качество'].total === 2);

  console.log('HTTP:');
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const h = await (await fetch(base + '/api/health')).json();
  check('health: 3 сервиса', h.ok && h.services === 3);
  const svcs = await (await fetch(base + '/api/services')).json();
  check('/api/services со ссылками на дашборды', svcs.services.length === 3 && svcs.services[0].dash);
  const st = await (await fetch(base + '/api/status')).json();
  check('/api/status: живой снимок', st.up === 2 && st.down === 1);
  const q = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"кто упал?"}' })).json();
  check('ask: перечисляет offline', /Сервис C|offline/i.test(q.reply) && q.engine === 'rules');

  srv.close(); a.close(); b.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
