// smoke.mjs — инварианты расчётного слоя под случайной нагрузкой + точечные кейсы.
// Property-style: гоняем сотни случайных расчётов (часть — с недостатком средств
// или неподтверждённой поставкой) и после КАЖДОГО проверяем: масса денег сохранена,
// овердрафтов нет, висящих резервов нет. Плюс точечно: атомарность многоплечевого,
// идемпотентность, эскроу reserve→capture/release, реверс. И то же по HTTP.
import http from 'node:http';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { createBook } = require('../book');
const { createEngine } = require('../settlement');
const invariants = require('../invariants');
const app = require('../server');

let passed = 0;
const ok = (c, m) => { assert.ok(c, m); console.log('  ✓', m); passed++; };
function mulberry32(seed) { let t = seed >>> 0; return () => { t += 0x6d2b79f5; let x = Math.imul(t ^ (t >>> 15), 1 | t); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }

async function main() {
  console.log('Property: инварианты держатся под случайной нагрузкой:');
  const book = createBook();
  const engine = createEngine(book);
  const names = ['buyer', 'seller', 'escrow', 'platform', 'agentA', 'agentB'];
  const starts = { buyer: 1000, seller: 500, escrow: 0, platform: 0, agentA: 800, agentB: 300 };
  for (const n of names) book.open(n, starts[n]);
  const TOTAL = book.totalMoney();
  ok(TOTAL === 2600, `начальная масса денег = ${TOTAL}`);

  const rnd = mulberry32(2024);
  let settled = 0, aborted = 0;
  for (let i = 0; i < 500; i++) {
    const from = names[Math.floor(rnd() * names.length)];
    let to = names[Math.floor(rnd() * names.length)]; if (to === from) to = names[(names.indexOf(from) + 1) % names.length];
    const amount = Math.round(rnd() * 400 * 100) / 100;
    const twoLeg = rnd() < 0.35;
    const legs = twoLeg ? [{ from, to: 'escrow', amount }, { from: 'escrow', to, amount }] : [{ from, to, amount }];
    const rec = engine.settle({ id: 's' + i, legs, deliver: rnd() < 0.85, ts: i });
    rec.state === 'settled' ? settled++ : aborted++;
    const inv = invariants.check(book, engine, TOTAL);
    if (!inv.ok) { console.error('НАРУШЕНИЕ на шаге', i, inv, rec); }
    assert.ok(inv.ok, `инварианты на шаге ${i}`);
  }
  ok(true, `500 случайных расчётов: settled ${settled}, aborted ${aborted} — инварианты держались на КАЖДОМ шаге`);
  ok(invariants.check(book, engine, TOTAL).total === TOTAL, 'масса денег сохранена после всей нагрузки');
  ok(book.activeHolds().length === 0, 'ни одного висящего резерва после нагрузки');

  console.log('Атомарность многоплечевого расчёта:');
  const b2 = createBook(); const e2 = createEngine(b2);
  b2.open('x', 100); b2.open('y', 0); b2.open('z', 0);
  const bad = e2.settle({ id: 'm1', legs: [{ from: 'x', to: 'y', amount: 100 }, { from: 'y', to: 'z', amount: 150 }] }); // 2-е плечо underfunded
  ok(bad.state === 'aborted' && bad.postings.length === 0, 'при провале 2-го плеча весь расчёт откатан (нет частичного эффекта)');
  ok(b2.get('x').balance === 100 && b2.get('y').balance === 0, 'балансы не изменились после атомарного отката');

  console.log('Идемпотентность:');
  const dup1 = e2.settle({ id: 'm2', legs: [{ from: 'x', to: 'y', amount: 40 }] });
  const dup2 = e2.settle({ id: 'm2', legs: [{ from: 'x', to: 'y', amount: 40 }] });
  ok(dup1 === dup2 && b2.get('x').balance === 60, 'повтор расчёта с тем же id применён РОВНО один раз');

  console.log('Эскроу reserve→capture/release:');
  const b3 = createBook(); b3.open('p', 300); b3.open('q', 0);
  const hid = b3.reserve('p', 120);
  ok(hid && b3.available('p') === 180 && b3.get('p').balance === 300, 'reserve удерживает средства (available падает, balance нет)');
  b3.capture(hid, 'q');
  ok(b3.get('p').balance === 180 && b3.get('q').balance === 120 && b3.activeHolds().length === 0, 'capture превращает резерв в перевод');
  const hid2 = b3.reserve('p', 50); b3.release(hid2);
  ok(b3.available('p') === 180 && b3.activeHolds().length === 0, 'release снимает резерв без движения средств');

  console.log('Реверс расчёта (спор/возврат):');
  const b4 = createBook(); const e4 = createEngine(b4);
  b4.open('u', 200); b4.open('v', 0);
  e4.settle({ id: 'r1', legs: [{ from: 'u', to: 'v', amount: 80 }] });
  const rev = e4.reverse('r1');
  ok(rev.state === 'settled' && b4.get('u').balance === 200 && b4.get('v').balance === 0, 'реверс возвращает балансы в исходное состояние');
  b4.transfer('v', 'u', 0); // no-op
  const rev2 = e4.reverse('r1'); ok(rev2.id === rev.id, 'повторный реверс идемпотентен (тот же результат)');
  // реверс невозможен, если получатель потратил
  b4.open('w', 0); e4.settle({ id: 'r2', legs: [{ from: 'u', to: 'v', amount: 100 }] }); b4.transfer('v', 'w', 100);
  const revFail = e4.reverse('r2');
  ok(revFail.state === 'aborted', 'реверс отклонён, если получатель уже распорядился средствами (без частичного эффекта)');

  console.log('HTTP через server.js:');
  const api = await new Promise((r) => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  const base = `http://127.0.0.1:${api.address().port}`;
  const call = (m, p, body) => new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : ''; const u = new URL(base + p);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: m, headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
      (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve({ status: res.statusCode, body: d ? JSON.parse(d) : {} }); } catch (e) { reject(e); } }); });
    req.on('error', reject); req.end(data);
  });
  await call('POST', '/api/accounts', { id: 'A', initial: 500 });
  await call('POST', '/api/accounts', { id: 'B', initial: 0 });
  const st = await call('POST', '/api/settle', { id: 'h1', legs: [{ from: 'A', to: 'B', amount: 200 }] });
  ok(st.status === 200 && st.body.settlement.state === 'settled' && st.body.invariants.ok, 'POST /api/settle проводит расчёт, инварианты держатся');
  const acc = await call('GET', '/api/accounts');
  ok(acc.body.total === 500 && acc.body.accounts.find((a) => a.id === 'B').balance === 200, 'масса денег сохранена, B получил 200');
  const badHttp = await call('POST', '/api/settle', { id: 'h2', legs: [{ from: 'B', to: 'A', amount: 999 }] });
  ok(badHttp.body.settlement.state === 'aborted' && badHttp.body.invariants.ok, 'расчёт с нехваткой средств атомарно отклонён');
  const revHttp = await call('POST', '/api/reverse', { settlementId: 'h1' });
  ok(revHttp.body.result.state === 'settled', 'POST /api/reverse возвращает средства');
  const inv = await call('GET', '/api/verify-invariants');
  ok(inv.body.ok && inv.body.total === 500, 'GET /api/verify-invariants подтверждает целостность');
  const askResp = await call('POST', '/api/ask', { message: 'сохраняется ли масса денег?' });
  ok(/сохранена|инвариант/i.test(askResp.body.reply), '/api/ask объясняет инварианты словами');

  api.close();
  console.log(`\nВсе проверки пройдены (${passed}).`);
}

main().catch((e) => { console.error('ПРОВАЛ:', e); process.exit(1); });
