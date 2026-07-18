// runner.js — прогон эвал-кейсов против цели и сборка scorecard.
const { client } = require('./http');
const cases = require('./cases');

async function runCase(c, ctx) {
  const t0 = Date.now();
  try {
    const out = await c.run(ctx);
    return { id: c.id, name: c.name, weight: c.weight, pass: !!out.pass, detail: out.detail || '', ms: Date.now() - t0 };
  } catch (e) {
    return { id: c.id, name: c.name, weight: c.weight, pass: false, detail: 'ошибка: ' + e.message, ms: Date.now() - t0 };
  }
}

function score(results) {
  const total = results.reduce((s, r) => s + r.weight, 0) || 1;
  const got = results.reduce((s, r) => s + (r.pass ? r.weight : 0), 0);
  return Math.round((got / total) * 1000) / 10; // 0..100
}

// контрактный набор — последовательно (кейсы делят состояние: токен заказа)
async function runContract(base, atFn) {
  const http = client(base);
  const ctx = { http, state: {} };
  const results = [];
  for (const c of cases.contract) results.push(await runCase(c, ctx));
  return { suite: 'contract', target: http.url, at: atFn ? atFn() : null, score: score(results), passed: results.filter((r) => r.pass).length, total: results.length, results };
}

// поведенческий набор — против /api/chat витрины
async function runBehavior(base, atFn) {
  const http = client(base);
  const sid = 'eval-' + (atFn ? atFn() : 'x');
  const chat = async (message) => (await http.post('/api/chat', { sessionId: sid, message })).body;
  const ctx = { chat };
  const results = [];
  for (const c of cases.behavior) results.push(await runCase(c, ctx));
  return { suite: 'behavior', target: http.url, at: atFn ? atFn() : null, score: score(results), passed: results.filter((r) => r.pass).length, total: results.length, results };
}

module.exports = { runContract, runBehavior, score };
