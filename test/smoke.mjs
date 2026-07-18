// smoke.mjs — губернатор в контуре с двойником.
// Проверяем: разумный дозаказ ДОПУЩЕН (безопасно+выгодно), безрассудный дозаказ
// ЗАБЛОКИРОВАН (неплатёжеспособность) с рекомендацией безопасной альтернативы,
// вредная переоценка ЗАБЛОКИРОВАНА (не лучше бездействия). Плюс инварианты
// симуляции, детерминизм и HTTP.
import http from 'node:http';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const sim = require('../sim');
const governor = require('../governor');
const app = require('../server');

let passed = 0;
const ok = (c, m) => { assert.ok(c, m); console.log('  ✓', m); passed++; };

async function main() {
  const state = sim.defaultState();

  console.log('Инварианты симуляции:');
  const noop = sim.rollForward(state, { type: 'noop' }, { steps: 10 });
  ok(noop.endStock >= 0 && noop.minCash >= 0, 'бездействие: сток неотрицателен, кэш не уходит в минус');
  const r = sim.rollForward(state, { type: 'reorder', productId: 'rose', quantity: 20 }, { steps: 10 });
  ok(Math.abs(r.endCash - (state.cash - r.reorderSpend + r.revenue)) < 0.01, 'учёт кэша сходится: endCash = start − закупка + выручка');

  console.log('Разумный дозаказ — ДОПУЩЕН:');
  const ev1 = governor.evaluate(state, { type: 'reorder', productId: 'rose', quantity: 25 });
  ok(ev1.decision === 'admit', `дозаказ 25 роз допущен (${ev1.reason})`);
  ok(ev1.uplift > 0 && ev1.simulated.profit > ev1.baseline.profit, `прогноз выгоднее бездействия (uplift ${ev1.uplift})`);
  ok(ev1.simulated.minCash >= 0, 'платёжеспособность сохранена');

  console.log('Безрассудный дозаказ — ЗАБЛОКИРОВАН:');
  const ev2 = governor.evaluate(state, { type: 'reorder', productId: 'rose', quantity: 100 });
  ok(ev2.decision === 'block' && ev2.violations.some((v) => v.code === 'insolvency'), 'дозаказ 100 роз заблокирован по неплатёжеспособности');
  ok(ev2.recommendation && ev2.recommendation.action.type === 'reorder' && ev2.recommendation.action.quantity < 100, `рекомендована безопасная меньшая закупка (${ev2.recommendation.action.quantity})`);
  ok(governor.evaluate(state, ev2.recommendation.action).decision === 'admit', 'рекомендованная альтернатива сама проходит губернатора');

  console.log('Вредная переоценка — ЗАБЛОКИРОВАНА:');
  const ev3 = governor.evaluate(state, { type: 'reprice', productId: 'tulip', newPrice: 180 });
  ok(ev3.decision === 'block', `удвоение цены тюльпана заблокировано (${ev3.reason})`);
  ok(ev3.simulated.profit < ev3.baseline.profit, 'прогноз прибыли ниже базовой (спрос обвалился)');
  ok(ev3.simulated.spoilageUnits > ev3.baseline.spoilageUnits, 'выросла порча непроданного товара');

  console.log('Эскалация при мягком риске:');
  // дозаказ, который безопасен и выгоден, но оставляет высокий дефицит → эскалация
  const evEsc = governor.evaluate(state, { type: 'reorder', productId: 'rose', quantity: 8 });
  ok(['admit', 'escalate'].includes(evEsc.decision), `малый дозаказ: ${evEsc.decision}`);

  console.log('Детерминизм:');
  const again = governor.evaluate(state, { type: 'reorder', productId: 'rose', quantity: 25 });
  ok(JSON.stringify(again.simulated) === JSON.stringify(ev1.simulated) && again.decision === ev1.decision, 'повтор даёт тот же прогноз и решение');
  // губернатор не мутирует переданное состояние
  ok(state.products.find((p) => p.id === 'rose').stock === 5 && state.cash === 5000, 'оценка не изменила исходное состояние магазина');

  console.log('HTTP через server.js:');
  const api = await new Promise((res) => { const s = app.listen(0, '127.0.0.1', () => res(s)); });
  const base = `http://127.0.0.1:${api.address().port}`;
  const post = (p, body) => new Promise((resolve, reject) => {
    const dta = JSON.stringify(body || {}); const u = new URL(base + p);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(dta) } },
      (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(d) }); } catch (e) { reject(e); } }); });
    req.on('error', reject); req.end(dta);
  });
  const a1 = await post('/api/propose', { action: { type: 'reorder', productId: 'rose', quantity: 25 } });
  ok(a1.status === 200 && a1.body.decision === 'admit', 'POST /api/propose допускает разумный дозаказ');
  const a2 = await post('/api/propose', { action: { type: 'reorder', productId: 'rose', quantity: 100 } });
  ok(a2.body.decision === 'block' && a2.body.recommendation, 'POST /api/propose блокирует безрассудный дозаказ и рекомендует альтернативу');
  const ask = await post('/api/ask', { message: 'почему заблокировали?' });
  ok(/insolvency|неплатёж|блок/i.test(ask.body.reply), '/api/ask объясняет блокировку словами');

  api.close();
  console.log(`\nВсе проверки пройдены (${passed}).`);
}

main().catch((e) => { console.error('ПРОВАЛ:', e); process.exit(1); });
