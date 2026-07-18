// test/smoke.mjs — проверка автономной петли и её предохранителей.
// Шлюз (авто vs эскалация), одобрение/отклонение, cooldown, сухой прогон vs
// реальное исполнение, kill-switch, лимит действий за цикл, HTTP.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;
const DAY = 86_400_000;

const store = require('../store.js');
const engine = require('../engine.js');
const policy = require('../policy.js');

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

// продукт-ряды: 10 суточных снимков
const SERIES = {
  A: { id: 1, name: 'A-cheap', price: 1.0, stock: [42, 39, 36, 33, 30, 27, 24, 21, 18, 15] }, // спрос 3, дешёвый дозаказ → авто
  B: { id: 2, name: 'B-pricey', price: 2.0, stock: [78, 72, 66, 60, 54, 48, 42, 36, 30, 24] }, // спрос 6, дорогой дозаказ → эскалация
  C: { id: 3, name: 'C-slow', price: 1.5, stock: [50, 50, 50, 50, 50, 50, 50, 50, 50, 50] },  // без продаж → скидка (эскалация)
  D: { id: 4, name: 'D-cheap2', price: 1.0, stock: [28, 26, 24, 22, 20, 18, 16, 14, 12, 10] }, // спрос 2, дешёвый → авто
};
function seed(keys) {
  store._reset();
  const items = keys.map((k) => SERIES[k]);
  for (let i = 0; i < 10; i++) store.recordSnapshot(items.map((s) => ({ id: s.id, name: s.name, price: s.price, stock: s.stock[i] })), i * DAY);
}

async function main() {
  console.log('шлюз: авто vs эскалация (сухой прогон):');
  policy.dryRun = true; policy.autoThreshold = 30; policy.maxActionsPerCycle = 5; policy.cooldownCycles = 3;
  seed(['A', 'B', 'C']);
  const s1 = await engine.cycle();
  check('предложено 3 действия', s1.proposed === 3);
  check('авто-исполнено 1 (дешёвый дозаказ A)', s1.auto_executed === 1);
  check('эскалировано 2 (дорогой дозаказ + цена)', s1.queued === 2 && store.pendingList.length === 2);
  check('в ledger 1 запись, помечена сухой', store.ledgerList.length === 1 && store.ledgerList[0].dryRun === true);
  check('авто-действие — про товар A', store.ledgerList[0].action.name === 'A-cheap');

  console.log('одобрение / отклонение:');
  const pend = store.pendingList.map((a) => a.id);
  const reorderB = pend.find((id) => id.includes('reorder'));
  const priceC = pend.find((id) => id.includes('price'));
  const ap = await engine.approve(reorderB);
  check('одобрение дорогого дозаказа → исполнено', ap.ok === true && store.ledgerList.length === 2);
  const rj = engine.reject(priceC, 'не сейчас');
  check('отклонение смены цены', rj.ok === true && store.pendingList.length === 0);
  check('аудит содержит approved и rejected', store.auditList.some((e) => e.event === 'approved') && store.auditList.some((e) => e.event === 'rejected'));

  console.log('cooldown:');
  const s2 = await engine.cycle(); // тот же ряд, cycle 2
  check('товар A под cooldown → пропущен', s2.skipped.some((x) => x.reason === 'cooldown') && !s2.details.some((d) => d.decision === 'auto-simulated' && d.id.includes('p1')));

  console.log('реальное исполнение (не сухой прогон):');
  policy.dryRun = false;
  seed(['A']);
  const s3 = await engine.cycle();
  check('A авто-исполнен по-настоящему', s3.auto_executed === 1);
  const last = store.ledgerList[store.ledgerList.length - 1];
  check('запись не сухая, эффектор ledger', last.dryRun === false && last.result.via === 'ledger' && /дозаказ/.test(last.result.effect));

  console.log('kill-switch:');
  policy.dryRun = true; seed(['A', 'B']);
  store.pause();
  const s4 = await engine.cycle();
  check('на паузе цикл ничего не делает', s4.paused === true);
  store.resume();

  console.log('лимит действий за цикл:');
  policy.maxActionsPerCycle = 1; seed(['A', 'D']); // оба дешёвые → авто-кандидаты
  const s5 = await engine.cycle();
  check('исполнено ровно 1 при лимите 1', s5.auto_executed === 1);
  check('второе — пропущено по rate-limit', s5.skipped.some((x) => x.reason === 'rate-limit'));
  policy.maxActionsPerCycle = 5;

  // ---- HTTP ----
  console.log('HTTP:');
  const backend = http.createServer((req, res) => {
    if (req.url === '/api/products') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify([{ id: 1, name: 'A', price: 1, stock: 10 }])); }
    res.writeHead(404); res.end('{}');
  });
  const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));
  const bport = await listen(backend);
  process.env.BACKEND_URL = `http://localhost:${bport}`;
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const get = async (p) => (await fetch(base + p)).json();
  const post = async (p, b) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined })).json();

  const h = await get('/api/health');
  check('движок rule-based', h.engine === 'rules');
  const snap = await post('/api/snapshot');
  check('снимок через контракт записан', snap.ok === true && snap.snapshots >= 1);

  // сквозной шлюз через HTTP: seed напрямую + /api/cycle
  policy.dryRun = true; seed(['A', 'B', 'C']);
  const cyc = await post('/api/cycle', {});
  check('HTTP cycle: 1 авто, 2 в очередь', cyc.auto_executed === 1 && cyc.queued === 2);
  const pj = await get('/api/pending');
  check('HTTP pending: 2 действия', pj.pending.length === 2);
  const okApprove = await post('/api/approve/' + pj.pending[0].id);
  check('HTTP approve работает', okApprove.ok === true);
  await post('/api/pause');
  const paused = await post('/api/cycle', {});
  check('HTTP pause останавливает цикл', paused.paused === true);
  const q = await post('/api/ask', { message: 'что в очереди на одобрение?' });
  check('HTTP ask (rules) отвечает', typeof q.reply === 'string' && q.engine === 'rules');

  srv.close(); backend.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}

main().catch((e) => { console.error(e); process.exit(1); });
