// smoke.mjs — жизненный цикл выката модели-ученика.
// Сценарий: v1 (полное обучение) проходит гейт и идёт в продакшн; v2 (недоучена)
// отклоняется канареечным гейтом; v3 обучена БЕЗ класса «order» и проходит слепой
// канареечный набор (тоже без order) — но на живом order-heavy трафике проседает
// ниже SLO → АВТО-ОТКАТ к v1. Детерминизм + HTTP.
import http from 'node:http';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const model = require('../model');
const data = require('../data');
const teacher = require('../teacher');
const { createRegistry } = require('../registry');
const pipeline = require('../pipeline');
const app = require('../server');

let passed = 0;
const ok = (c, m) => { assert.ok(c, m); console.log('  ✓', m); passed++; };

const ALL = teacher.CLASSES;
const NOORDER = ['catalog', 'price', 'greeting', 'other'];
const ORDER_HEAVY = ['order', 'order', 'order', 'order', 'catalog'];

async function main() {
  console.log('Обучение и качество модели:');
  const trainFull = data.generate(300, 1);
  const v1 = model.train(trainFull, { epochs: 200 });
  const evalFull = data.generate(200, 99);
  const agr1 = model.agreement(v1, evalFull);
  ok(agr1 >= 0.9, `полностью обученная модель согласна с учителем на ${agr1} (≥0.9)`);
  const undertrained = model.train(trainFull, { epochs: 0 });
  ok(model.agreement(undertrained, evalFull) < pipeline.FLOOR, 'недоученная (0 эпох) модель ниже SLO');

  console.log('Гейт и промоушен:');
  const reg = createRegistry();
  const d1 = pipeline.deploy(reg, 'v1', v1, evalFull);
  ok(d1.promoted && reg.production() === 'v1', 'v1 прошла гейт и стала продакшн');
  const d2 = pipeline.deploy(reg, 'v2', undertrained, evalFull);
  ok(!d2.promoted && d2.state === 'rejected' && reg.production() === 'v1', 'недоученная v2 отклонена гейтом, продакшн остался v1');

  console.log('Слепой канареечный набор пропускает v3 (blindspot):');
  const trainNo = data.generate(300, 2, { classes: NOORDER });
  const v3 = model.train(trainNo, { epochs: 200, classes: NOORDER });
  const evalNo = data.generate(200, 98, { classes: NOORDER });
  const d3 = pipeline.deploy(reg, 'v3', v3, evalNo);
  ok(d3.promoted && reg.production() === 'v3', `v3 прошла слепой канареечный набор (согласие ${d3.canaryAgreement}) и стала продакшн`);

  console.log('Живой order-heavy трафик → авто-откат:');
  const liveOrder = data.generate(160, 777, { classes: ORDER_HEAVY });
  const mon = pipeline.monitor(reg, liveOrder);
  ok(mon.breached && mon.liveAgreement < pipeline.FLOOR, `живое согласие v3 просело до ${mon.liveAgreement} (< SLO ${pipeline.FLOOR})`);
  ok(mon.rolledBack && reg.production() === 'v1', 'сработал авто-откат к последней хорошей версии v1');
  ok(reg.incidents().length === 1 && reg.incidents()[0].to === 'v1', 'инцидент отката записан');
  const monAfter = pipeline.monitor(reg, liveOrder);
  ok(!monAfter.breached && monAfter.liveAgreement >= pipeline.FLOOR, `после отката v1 держит order-heavy трафик (${monAfter.liveAgreement})`);

  console.log('Инференс продакшн-модели:');
  const predict = model.predictor(reg.get(reg.production()).artifact);
  ok(predict('сколько стоит роза').label === 'price' && predict('хочу оформить заказ').label === 'order', 'продакшн-модель (v1) верно классифицирует price и order');

  console.log('Детерминизм:');
  const v1b = model.train(data.generate(300, 1), { epochs: 200 });
  ok(JSON.stringify(v1b.b) === JSON.stringify(v1.b) && JSON.stringify(v1b.W[0]) === JSON.stringify(v1.W[0]), 'повторное обучение даёт идентичные веса');

  console.log('HTTP через server.js:');
  const api = await new Promise((r) => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  const base = `http://127.0.0.1:${api.address().port}`;
  const post = (p, body) => new Promise((resolve, reject) => {
    const dta = JSON.stringify(body || {}); const u = new URL(base + p);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(dta) } },
      (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(d) }); } catch (e) { reject(e); } }); });
    req.on('error', reject); req.end(dta);
  });
  const h1 = await post('/api/deploy', { version: 'p1', epochs: 200 });
  ok(h1.body.promoted, 'POST /api/deploy обучает и промоутит первую версию');
  const pr = await post('/api/predict', { text: 'покажи каталог' });
  ok(pr.body.version === 'p1' && pr.body.label === 'catalog', 'POST /api/predict отдаёт предсказание продакшн-модели');
  const hb = await post('/api/deploy', { version: 'p-blind', classes: NOORDER, evalClasses: NOORDER, epochs: 200 });
  ok(hb.body.promoted, 'слепая версия p-blind промоучена (канареечный набор без order)');
  const hm = await post('/api/monitor', { classes: ORDER_HEAVY, size: 160, seed: 777 });
  ok(hm.body.breached && hm.body.rolledBack && hm.body.rollback.to === 'p1', 'POST /api/monitor ловит дрейф и авто-откатывает к p1');
  const ask = await post('/api/ask', { message: 'были ли откаты?' });
  ok(/откат|инцидент/i.test(ask.body.reply), '/api/ask сообщает об авто-откате словами');

  api.close();
  console.log(`\nВсе проверки пройдены (${passed}).`);
}

main().catch((e) => { console.error('ПРОВАЛ:', e); process.exit(1); });
