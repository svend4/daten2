// predicates.js — стражи безопасности/выгоды над прогнозом симуляции.
// hard — жёсткие запреты (никогда не пропускать); soft — поводы к эскалации.
const DEFAULTS = { maxSpoilageRate: 0.35, maxStockoutRate: 0.6, benefitTol: 0.03 };

function beneficial(sim, noop, cfg = DEFAULTS) {
  return sim.profit >= noop.profit - Math.abs(noop.profit) * cfg.benefitTol;
}

function evaluate(sim, noop, cfg = DEFAULTS) {
  const v = [];
  if (sim.minCash < 0) v.push({ code: 'insolvency', severity: 'hard', detail: `минимальный кэш ${sim.minCash} < 0` });
  if (sim.spoilageRate > cfg.maxSpoilageRate) v.push({ code: 'excessive-waste', severity: 'hard', detail: `порча ${Math.round(sim.spoilageRate * 100)}% > ${Math.round(cfg.maxSpoilageRate * 100)}%` });
  if (sim.stockoutRate > cfg.maxStockoutRate) v.push({ code: 'understocked', severity: 'soft', detail: `дефицит ${Math.round(sim.stockoutRate * 100)}% шагов` });
  if (!beneficial(sim, noop, cfg)) v.push({ code: 'not-beneficial', severity: 'soft', detail: `прибыль ${sim.profit} < базовой ${noop.profit}` });
  return v;
}
module.exports = { evaluate, beneficial, DEFAULTS };
