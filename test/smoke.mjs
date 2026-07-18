// test/smoke.mjs — проверка green/FinOps-роутера.
// Три уровня с разным профилем: A быстрый, B дешёвый, C зелёный. Проверяем, что
// веса смещают выбор, что учитываются €/энергия/CO2 и что работает прокси+FinOps.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

function level(delay) {
  return http.createServer((req, res) => {
    const respond = () => {
      if (req.url === '/api/health') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end('{"ok":true}'); }
      if (req.url.startsWith('/api/products')) { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify([{ id: 1, name: 'Роза', price: 1.5 }])); }
      res.writeHead(404); res.end('{}');
    };
    if (delay) setTimeout(respond, delay); else respond();
  });
}
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const A = level(5), B = level(80), C = level(30);
  const [pa, pb, pc] = await Promise.all([listen(A), listen(B), listen(C)]);
  // A: быстрый, средняя цена/углерод; B: медленный, дешёвый; C: средний, зелёный
  process.env.ROUTER_BACKENDS = JSON.stringify([
    { id: 'A', name: 'A-fast',  url: `http://localhost:${pa}`, cost: 0.003, watts: 20, grid: 400 },
    { id: 'B', name: 'B-cheap', url: `http://localhost:${pb}`, cost: 0.001, watts: 15, grid: 100 },
    { id: 'C', name: 'C-green', url: `http://localhost:${pc}`, cost: 0.002, watts: 30, grid: 20 },
  ]);

  const registry = require('../registry.js');
  const model = require('../model.js');
  model.configure(registry.backends);
  await model.refresh();

  console.log('CO2-модель:');
  const co2A = model.co2mg(registry.backends[0], 5), co2C = model.co2mg(registry.backends[2], 30);
  check('CO2 считается (>0)', co2A > 0 && co2C > 0);
  check('зелёная сеть (C, grid 20) чище грязной (A, grid 400) при равной энергии', model.co2mg({ watts: 20, grid: 20 }, 10) < model.co2mg({ watts: 20, grid: 400 }, 10));

  console.log('веса смещают выбор:');
  model.setWeights({ latency: 1, cost: 0, carbon: 0, reliability: 0 });
  check('приоритет скорости → A (быстрый)', model.decide().choice === 'A');
  model.setWeights({ latency: 0, cost: 1, carbon: 0, reliability: 0 });
  check('приоритет цены → B (дешёвый)', model.decide().choice === 'B');
  model.setWeights({ latency: 0, cost: 0, carbon: 1, reliability: 0 });
  check('приоритет экологии → C (зелёный)', model.decide().choice === 'C');
  model.setWeights({ latency: 0.4, cost: 0.3, carbon: 0.2, reliability: 0.1 });
  const bal = model.decide();
  check('сбалансированный режим даёт корректный composite', bal.scored.every((s) => s.composite >= 0 && s.composite <= 1));

  console.log('HTTP + FinOps:');
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app); const port = await listen(srv);
  const base = `http://localhost:${port}`;
  await fetch(base + '/api/router/refresh', { method: 'POST' });
  // выставим приоритет цены → трафик на B
  await fetch(base + '/api/weights', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ latency: 0, cost: 1, carbon: 0, reliability: 0 }) });
  let served = null;
  for (let i = 0; i < 5; i++) { const r = await fetch(base + '/api/products'); served = r.headers.get('x-served-by-level'); }
  check('прокси обслуживает выбранный уровень (B)', served === 'B');
  const fin = await (await fetch(base + '/api/router/finops')).json();
  check('FinOps: учтены запросы и деньги', fin.total.req >= 5 && fin.total.costEur > 0);
  check('FinOps: учтены энергия и CO2', fin.total.energyWh > 0 && fin.total.co2g > 0);
  check('заголовок X-CO2-mg присутствует', (await fetch(base + '/api/products')).headers.get('x-co2-mg') != null);

  const dec = await (await fetch(base + '/api/router/decide')).json();
  check('decide возвращает composite/латентность/цену/CO2', dec.scored[0].composite != null && dec.scored[0].co2mg != null && dec.scored[0].costEur != null);
  const q = await (await fetch(base + '/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'сколько потрачено?' }) })).json();
  check('ask (rules) про FinOps', /потрачено|€/i.test(q.reply) && q.engine === 'rules');

  srv.close(); A.close(); B.close(); C.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
