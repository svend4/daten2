// runner.js — движок chaos-экспериментов: применить сбои → нагрузка через устойчивый
// фронт → проверить гипотезу SLO → восстановить. «pass» = система повела себя как
// ожидалось (SLO держится при частичном отказе; ломается только при полном).
const targetsMod = require('./targets');
const resilient = require('./resilient');
const load = require('./load');
const slo = require('./slo');
const experiments = require('./experiments');

async function runOne(exp, opts) {
  targetsMod.clearFaults();
  for (const f of exp.faults) {
    const id = f.target === 'all' ? 'all' : targetsMod.targets[f.target].id;
    targetsMod.setFault(id, f);
  }
  const metrics = await load.run(() => resilient.request(targetsMod.targets, { method: 'GET', path: '/api/products' }), opts);
  const sloRes = slo.check(metrics, exp.hypothesis);
  targetsMod.clearFaults();
  const held = sloRes.ok;                 // держится ли SLO по факту
  const pass = held === exp.expectSlo;    // совпало ли с ожиданием
  return { id: exp.id, name: exp.name, expectSlo: exp.expectSlo, held, pass, metrics, violations: sloRes.violations };
}

async function runAll(opts = {}) {
  const results = [];
  for (const exp of experiments) results.push(await runOne(exp, opts));
  const passed = results.filter((r) => r.pass).length;
  return { passed, total: results.length, allPass: passed === results.length, results };
}

module.exports = { runAll, runOne };
