// smoke.mjs — проверка off-policy оценщика на среде со СКРЫТОЙ истиной.
// Логирующая политика — ε-жадная по (мискалиброванному) `predicted` — гоняется
// онлайн; истинные награды известны только среде (не оценщику). Проверяем, что
// оценщик из ОДНОГО журнала честно восстанавливает: (1) равномерная политика ≈
// средняя истинная награда, (2) лучшая по факту политика («fastest») превосходит
// логирующую → положительный regret, хотя её никогда не выкатывали; и что хэш-цепь
// журнала tamper-evident. Плюс HTTP через server.js. Детерминированно (mulberry32).
import http from 'node:http';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { createLedger } = require('../ledger');
const ope = require('../ope');
const { verifyChain } = require('../hashchain');
const app = require('../server');

let passed = 0;
const ok = (c, m) => { assert.ok(c, m); console.log('  ✓', m); passed++; };
const near = (a, b, tol, m) => ok(Math.abs(a - b) <= tol, `${m} (${Math.round(a * 1000) / 1000} ≈ ${b} ±${tol})`);

function mulberry32(seed) { let t = seed >>> 0; return () => { t += 0x6d2b79f5; let x = Math.imul(t ^ (t >>> 15), 1 | t); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }

// 4 действия: атрибуты видны политикам; trueR — СКРЫТАЯ истинная средняя награда.
// Замысел: `predicted` мискалиброван (максимум у A), а по факту лучший — B (он же
// самый быстрый). Значит off-policy должна показать: «fastest» > логирующей.
const ARMS = [
  { id: 'A', cost: 1, latency: 5, predicted: 0.9, reliability: 0.8, trueR: 0.40 },
  { id: 'B', cost: 2, latency: 1, predicted: 0.5, reliability: 0.9, trueR: 0.80 },
  { id: 'C', cost: 1, latency: 8, predicted: 0.7, reliability: 0.7, trueR: 0.50 },
  { id: 'D', cost: 3, latency: 3, predicted: 0.6, reliability: 0.95, trueR: 0.55 },
];
const actions = ARMS.map(({ id, cost, latency, predicted, reliability }) => ({ id, cost, latency, predicted, reliability }));
const trueR = Object.fromEntries(ARMS.map((a) => [a.id, a.trueR]));
const meanTrue = ARMS.reduce((s, a) => s + a.trueR, 0) / ARMS.length;

// ЛОГИРУЮЩАЯ политика: ε-жадная по predicted (argmax = A), ε=0.4 → p(A)=0.7, иначе 0.1
const EPS = 0.4, GREEDY = 'A';
const propen = (id) => (id === GREEDY ? 1 - EPS + EPS / ARMS.length : EPS / ARMS.length);

function buildLedger(n, seed) {
  const rnd = mulberry32(seed);
  const led = createLedger();
  for (let i = 0; i < n; i++) {
    // сэмплируем выбор логирующей политики
    let u = rnd(), chosen = ARMS[ARMS.length - 1].id;
    for (const a of ARMS) { const p = propen(a.id); if (u < p) { chosen = a.id; break; } u -= p; }
    const id = led.decision({ domain: 'router', context: { i }, actions, chosen, propensity: propen(chosen), ts: i });
    // наблюдаем награду ТОЛЬКО выбранного действия (истина + малый шум)
    const reward = trueR[chosen] + (rnd() - 0.5) * 0.1;
    led.outcome(id, reward);
  }
  return led;
}

async function main() {
  const led = buildLedger(6000, 12345);
  const decisions = led.state();

  console.log('Журнал и хэш-цепь:');
  ok(decisions.length === 6000 && led.resolvedCount() === 6000, 'все 6000 решений залогированы и разрешены');
  ok(led.verify().ok, 'хэш-цепь цела (append-only)');
  const tampered = led.events(); tampered[10] = { ...tampered[10], reward: 999 };
  ok(!verifyChain(tampered).ok, 'подмена события ломает цепь (tamper-evident)');

  console.log('Off-policy оценка честно восстанавливает истину:');
  const logged = ope.loggedValue(decisions);
  const expLogged = ARMS.reduce((s, a) => s + propen(a.id) * a.trueR, 0);
  near(logged, expLogged, 0.02, 'ценность логирующей политики ≈ теоретической');
  const uni = ope.evaluate(decisions, (c, acts) => Object.fromEntries(acts.map((a) => [a.id, 1 / acts.length])));
  near(uni.snips, meanTrue, 0.03, 'SNIPS равномерной политики ≈ средняя истинная награда');
  near(ope.evaluate(decisions, (c, acts) => ({ B: 1 })).snips, trueR.B, 0.03, 'SNIPS «всегда B» ≈ истинная награда B');

  console.log('Контрфакт: лучшая политика превосходит логирующую (не выкатывая её):');
  const cmp = ope.comparePolicies(decisions);
  ok(cmp.best === 'fastest', `лучшая из рассмотренных — «fastest» (а не жадная по predicted), выбрана ${cmp.best}`);
  const fastest = cmp.policies.find((p) => p.name === 'fastest');
  near(fastest.snips, trueR.B, 0.03, '«fastest» оценочно даёт награду арма B');
  ok(cmp.regret > 0.2, `regret логирующей политики против лучшей положителен (${cmp.regret})`);
  ok(cmp.policies.find((p) => p.name === 'greedy-reward').snips < fastest.snips, 'жадная по predicted (что деплоили) хуже fastest — мискалибровка вскрыта');
  ok(cmp.policies.every((p) => p.ess > 0 && p.overlap > 0), 'у всех политик положительные ESS и overlap');

  console.log('Детерминизм:');
  const cmp2 = ope.comparePolicies(buildLedger(6000, 12345).state());
  ok(JSON.stringify(cmp2.policies) === JSON.stringify(cmp.policies), 'повторная сборка журнала даёт те же оценки');

  console.log('HTTP через server.js:');
  const api = await new Promise((r) => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  const base = `http://127.0.0.1:${api.address().port}`;
  const post = (p, body) => new Promise((resolve, reject) => {
    const data = JSON.stringify(body || {}); const u = new URL(base + p);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
      (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(d) }); } catch (e) { reject(e); } }); });
    req.on('error', reject); req.end(data);
  });
  // прогоняем 400 решений через HTTP
  const rnd = mulberry32(999);
  for (let i = 0; i < 400; i++) {
    let u = rnd(), chosen = 'D'; for (const a of ARMS) { const p = propen(a.id); if (u < p) { chosen = a.id; break; } u -= p; }
    const dec = await post('/api/decision', { domain: 'router', context: { i }, actions, chosen, propensity: propen(chosen), ts: i });
    await post('/api/resolve', { id: dec.body.id, reward: trueR[chosen] + (rnd() - 0.5) * 0.1 });
  }
  const ev = await post('/api/evaluate', { policies: ['greedy-reward', 'fastest', 'uniform', 'cheapest'] });
  ok(ev.status === 200 && ev.body.best === 'fastest', 'POST /api/evaluate по HTTP выбирает «fastest» лучшей');
  ok(ev.body.regret > 0.1, 'HTTP-оценка показывает положительный regret логирующей политики');
  const chain = await post('/api/ask', { message: 'цела ли хэш-цепь?' });
  ok(/цел|append-only/i.test(chain.body.reply), '/api/ask подтверждает целостность цепи словами');
  const adv = await post('/api/ask', { message: 'какая политика лучше и что было бы?' });
  ok(/fastest|политик/i.test(adv.body.reply), '/api/ask объясняет контрфактуальное сравнение политик');

  api.close();
  console.log(`\nВсе проверки пройдены (${passed}).`);
}

main().catch((e) => { console.error('ПРОВАЛ:', e); process.exit(1); });
