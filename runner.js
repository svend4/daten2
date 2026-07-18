// runner.js — дифференциальная верификация языковых портов.
// Прогоняем ОДИН И ТОТ ЖЕ сценарий контракта против каждой реализации, проецируем
// ответы в каноническую форму и сравниваем все порты с эталоном (differential
// testing). Расхождение = один язык ведёт себя иначе на том же контракте.
const { client } = require('./client');
const P = require('./project');
const { deepDiff } = require('./diff');

const STEPS = ['health', 'products', 'create-order', 'get-order'];

// фиксированный заказ: 3×товар#1 + 2×товар#2 (id канонической схемы одинаковы у всех)
const ORDER = {
  items: [{ product_id: 1, quantity: 3 }, { product_id: 2, quantity: 2 }],
  customer: { name: 'Rosetta', email: 'rosetta@example.com', phone: '+10000000000', address: 'test' },
};

async function runScript(backend) {
  const c = client(backend.url);
  const steps = [];
  steps.push({ step: 'health', canonical: P.health(await c.health()) });
  steps.push({ step: 'products', canonical: P.products(await c.products()) });
  const created = await c.createOrder(ORDER);
  steps.push({ step: 'create-order', canonical: P.orderCreate(created) });
  const onum = created && (created.order_number || created.orderNumber || created.number);
  const got = onum ? await c.getOrder(onum) : {};
  steps.push({ step: 'get-order', canonical: P.orderGet(got) });
  return steps;
}

async function runAll(backends, { referenceName } = {}) {
  const runs = [];
  for (const b of backends) {
    try { runs.push({ name: b.name, url: b.url, ok: true, steps: await runScript(b) }); }
    catch (e) { runs.push({ name: b.name, url: b.url, ok: false, error: e.message, steps: [] }); }
  }
  const ref = runs.find((r) => r.name === referenceName && r.ok) || runs.find((r) => r.ok);
  const divergences = [];
  if (ref) {
    const refByStep = Object.fromEntries(ref.steps.map((s) => [s.step, s.canonical]));
    for (const r of runs) {
      if (r === ref || !r.ok) continue;
      for (const s of r.steps) for (const d of deepDiff(refByStep[s.step], s.canonical)) divergences.push({ backend: r.name, step: s.step, ...d });
    }
  }
  const byBackend = {};
  for (const r of runs) byBackend[r.name] = { ok: r.ok, error: r.error, divergent: divergences.filter((d) => d.backend === r.name).length, equivalent: r.ok && r !== ref ? divergences.filter((d) => d.backend === r.name).length === 0 : r.ok };
  return {
    reference: ref ? ref.name : null,
    backends: runs.map((r) => ({ name: r.name, url: r.url, ok: r.ok, error: r.error })),
    steps: STEPS,
    divergences,
    allEquivalent: divergences.length === 0 && runs.length > 0 && runs.every((r) => r.ok),
    byBackend,
  };
}

// waiver-подход: baseline фиксирует принятые расхождения; новое расхождение = регрессия
const keyOf = (d) => `${d.backend}|${d.step}|${d.path}`;
function compare(current, baseline) {
  if (!baseline) return { hasBaseline: false, newDivergences: current.divergences, resolved: [] };
  const base = new Set(baseline.divergences.map(keyOf));
  const cur = new Set(current.divergences.map(keyOf));
  return {
    hasBaseline: true,
    newDivergences: current.divergences.filter((d) => !base.has(keyOf(d))),
    resolved: baseline.divergences.filter((d) => !cur.has(keyOf(d))),
  };
}

module.exports = { runAll, compare, runScript, STEPS };
