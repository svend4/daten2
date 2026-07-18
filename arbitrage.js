// arbitrage.js — выигрыш углеродного арбитража: оптимизированный план против
// наивного baseline (всё «сейчас, дома»). Показывает сэкономленные CO2 и деньги.
const grid = require('./grid');
const { schedule } = require('./scheduler');

const r2 = (x) => Math.round(x * 100) / 100;
const r4 = (x) => Math.round(x * 10000) / 10000;

function plan(jobs, g, opts = {}) {
  const a = schedule(jobs, g, opts);
  const optCarbon = r2(a.reduce((s, x) => s + x.carbon, 0));
  const optCost = r4(a.reduce((s, x) => s + x.cost, 0));
  const naiveCarbon = r2(a.reduce((s, x) => s + x.naiveCarbon, 0));
  const naiveCost = r4(a.reduce((s, x) => s + x.naiveCost, 0));
  const shifted = a.filter((x) => x.shifted).length;
  return {
    T: g.T, weightCarbon: opts.weightCarbon == null ? 1 : opts.weightCarbon,
    jobs: a.length, shifted,
    naive: { carbon: naiveCarbon, cost: naiveCost },
    optimized: { carbon: optCarbon, cost: optCost },
    savings: {
      carbon: r2(naiveCarbon - optCarbon),
      cost: r4(naiveCost - optCost),
      carbonPct: naiveCarbon > 0 ? Math.round((1 - optCarbon / naiveCarbon) * 1000) / 10 : 0,
      costPct: naiveCost > 0 ? Math.round((1 - optCost / naiveCost) * 1000) / 10 : 0,
    },
    assignments: a,
  };
}

module.exports = { plan };
