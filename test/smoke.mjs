// smoke.mjs — проверки углеродного планировщика.
// Property: сотни случайных нагрузок — каждая размещена в допустимом регионе, до
// дедлайна, углерод не хуже наивного (при углеродной цели), ёмкость зелёных ячеек
// не превышена. Плюс точечно: отложимая работа сдвигается в зелёное окно, дедлайн
// мешает сдвигу, ёмкость выталкивает часть в менее зелёные ячейки, неотложимая
// пришпилена к «сейчас», ценовая цель выбирает дешёвое, а не зелёное. И HTTP.
import http from 'node:http';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const grid = require('../grid');
const arbitrage = require('../arbitrage');
const invariants = require('../invariants');
const app = require('../server');

let passed = 0;
const ok = (c, m) => { assert.ok(c, m); console.log('  ✓', m); passed++; };
function mulberry32(seed) { let t = seed >>> 0; return () => { t += 0x6d2b79f5; let x = Math.imul(t ^ (t >>> 15), 1 | t); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }

async function main() {
  const g = grid.generate(12);
  const regions = grid.REGIONS;

  console.log('Property: планы корректны под случайной нагрузкой:');
  const rnd = mulberry32(4242);
  let totalShiftBenefit = 0, runs = 0;
  for (let iter = 0; iter < 60; iter++) {
    const n = 3 + Math.floor(rnd() * 10);
    const jobs = Array.from({ length: n }, (_, i) => ({
      id: 'j' + iter + '_' + i,
      energy: Math.round((0.5 + rnd() * 5) * 100) / 100,
      deadline: Math.floor(rnd() * 12),
      deferrable: rnd() < 0.85,
      regions: rnd() < 0.5 ? regions : [regions[Math.floor(rnd() * regions.length)]],
    }));
    const capacityPerCell = rnd() < 0.5 ? Infinity : Math.round(rnd() * 8 * 100) / 100;
    const p = arbitrage.plan(jobs, g, { weightCarbon: 1, capacityPerCell });
    const inv = invariants.check(Object.fromEntries(jobs.map((j) => [j.id, j])), g, p, capacityPerCell);
    if (!inv.ok) { console.error('НАРУШЕНИЕ iter', iter, inv.problems.slice(0, 3)); }
    assert.ok(inv.ok, `инварианты плана iter ${iter}`);
    assert.ok(p.optimized.carbon <= p.naive.carbon + 1e-6, `оптимум ≤ наивного iter ${iter}`);
    totalShiftBenefit += p.savings.carbon; runs++;
  }
  ok(true, `60 случайных планов: дедлайны/регионы/ёмкость соблюдены, углерод ≤ наивного на КАЖДОМ`);
  ok(totalShiftBenefit > 0, `суммарный выигрыш CO2 по всем прогонам положителен (${Math.round(totalShiftBenefit)} г)`);

  console.log('Отложимая работа сдвигается в зелёное окно:');
  const p1 = arbitrage.plan([{ id: 'a', energy: 10, deadline: 11, deferrable: true, regions }], g, { weightCarbon: 1 });
  const a1 = p1.assignments[0];
  ok(a1.shifted && a1.region === 'eu-north', `работа ушла в самый чистый регион (${a1.region})`);
  ok(a1.carbon < a1.naiveCarbon, `углерод снижен (${a1.naiveCarbon}→${a1.carbon}) при экономии ${p1.savings.carbonPct}%`);

  console.log('Дедлайн ограничивает сдвиг:');
  const p2 = arbitrage.plan([{ id: 'b', energy: 10, deadline: 0, deferrable: true, regions }], g, { weightCarbon: 1 });
  ok(p2.assignments[0].slot === 0 && !p2.assignments[0].shifted, 'работа с дедлайном 0 не сдвигается (осталась «сейчас»)');

  console.log('Ёмкость выталкивает часть нагрузки:');
  const many = Array.from({ length: 6 }, (_, i) => ({ id: 'c' + i, energy: 5, deadline: 11, deferrable: true, regions: ['eu-north', 'eu-west'] }));
  const p3 = arbitrage.plan(many, g, { weightCarbon: 1, capacityPerCell: 5 }); // в ячейку влезает лишь одна работа
  const cellsUsed = new Set(p3.assignments.map((a) => a.region + ':' + a.slot));
  ok(cellsUsed.size >= 5, `ёмкость=5 заставила разложить работы по разным ячейкам (${cellsUsed.size})`);
  ok(invariants.check(Object.fromEntries(many.map((j) => [j.id, j])), g, p3, 5).ok, 'ёмкость нигде не превышена');

  console.log('Неотложимая работа пришпилена к «сейчас»:');
  const p4 = arbitrage.plan([{ id: 'd', energy: 10, deadline: 11, deferrable: false, regions }], g, { weightCarbon: 1 });
  ok(p4.assignments[0].slot === 0 && !p4.assignments[0].shifted, 'deferrable:false → слот 0, дома');

  console.log('Ценовая цель выбирает дешёвое, а не самое зелёное:');
  const carbonPlan = arbitrage.plan([{ id: 'e', energy: 10, deadline: 11, deferrable: true, regions }], g, { weightCarbon: 1 });
  const pricePlan = arbitrage.plan([{ id: 'e', energy: 10, deadline: 11, deferrable: true, regions }], g, { weightCarbon: 0 });
  ok(pricePlan.assignments[0].cost <= carbonPlan.assignments[0].cost + 1e-9, 'при weightCarbon=0 стоимость не выше, чем при углеродной цели');
  ok(pricePlan.assignments[0].region !== carbonPlan.assignments[0].region || pricePlan.assignments[0].slot !== carbonPlan.assignments[0].slot, 'ценовая и углеродная цели дают разный выбор окна');

  console.log('Детерминизм:');
  const again = arbitrage.plan(many, g, { weightCarbon: 1, capacityPerCell: 5 });
  ok(JSON.stringify(again.assignments) === JSON.stringify(p3.assignments), 'повтор даёт идентичный план');

  console.log('HTTP через server.js:');
  const api = await new Promise((r) => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  const base = `http://127.0.0.1:${api.address().port}`;
  const post = (p, body) => new Promise((resolve, reject) => {
    const data = JSON.stringify(body || {}); const u = new URL(base + p);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
      (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(d) }); } catch (e) { reject(e); } }); });
    req.on('error', reject); req.end(data);
  });
  const sched = await post('/api/schedule', { jobs: [{ id: 'x', energy: 10, deadline: 11, deferrable: true, regions }, { id: 'y', energy: 4, deadline: 3, deferrable: true, regions }], weightCarbon: 1 });
  ok(sched.status === 200 && sched.body.invariants.ok && sched.body.savings.carbon > 0, 'POST /api/schedule даёт корректный план с экономией CO2');
  const askResp = await post('/api/ask', { message: 'сколько CO2 сэкономили?' });
  ok(/арбитраж|co2|экономия/i.test(askResp.body.reply), '/api/ask объясняет выигрыш словами');

  api.close();
  console.log(`\nВсе проверки пройдены (${passed}).`);
}

main().catch((e) => { console.error('ПРОВАЛ:', e); process.exit(1); });
