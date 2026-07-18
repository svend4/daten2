// ope.js — OFF-POLICY EVALUATION. Оцениваем ценность ДРУГОЙ политики π по уже
// залогированным решениям, НЕ выкатывая её. Основа — inverse propensity scoring:
//
//   V(π) ≈ (1/n) Σ_i [ π(a_i | x_i) / p_i ] · r_i          (IPS, Horvitz–Thompson)
//
// где p_i — вероятность, с которой ЛОГИРУЮЩАЯ политика выбрала a_i (propensity),
// r_i — наблюдённая награда выбранного действия. Награды невыбранных действий
// НЕ используются и НЕ выдумываются — только перевзвешивание уже наблюдённого.
// SNIPS — самонормированный вариант (меньше дисперсия). ESS — эффективный размер
// выборки: мало общего носителя у π и логирующей политики → оценка ненадёжна.
const policies = require('./policies');

function evaluate(decisions, policyProb) {
  let sum = 0, wsum = 0, n = 0;
  const weights = [];
  for (const d of decisions) {
    if (d.reward == null) continue;
    n++;
    const pi = policyProb(d.context, d.actions)[d.chosen] || 0;
    const w = pi / Math.max(d.propensity, 1e-9);
    weights.push(w);
    sum += w * d.reward;
    wsum += w;
  }
  const sw = weights.reduce((s, w) => s + w, 0);
  const sw2 = weights.reduce((s, w) => s + w * w, 0);
  const ess = sw2 > 0 ? (sw * sw) / sw2 : 0;                         // эффективный размер выборки
  const overlap = n ? weights.filter((w) => w > 0).length / n : 0;   // доля решений с общим носителем
  return {
    n,
    ips: n ? sum / n : 0,
    snips: wsum ? sum / wsum : 0,
    ess: Math.round(ess * 100) / 100,
    overlap: Math.round(overlap * 1000) / 1000,
    confident: ess >= 30 && overlap >= 0.05,
  };
}

// эмпирическая ценность логирующей политики = среднее наблюдённых наград
function loggedValue(decisions) {
  const r = decisions.filter((d) => d.reward != null).map((d) => d.reward);
  return r.length ? r.reduce((s, x) => s + x, 0) / r.length : 0;
}

// сравнить набор именованных политик, посчитать regret против ЛУЧШЕЙ найденной
function comparePolicies(decisions, names) {
  const list = (names && names.length ? names : policies.names());
  const logged = loggedValue(decisions);
  const rows = list.map((name) => ({ name, ...evaluate(decisions, (ctx, actions) => policies.prob(name, ctx, actions)) }))
    .sort((a, b) => b.snips - a.snips);
  const best = rows.find((r) => r.confident) || rows[0];
  return {
    resolved: decisions.filter((d) => d.reward != null).length,
    loggedValue: Math.round(logged * 10000) / 10000,
    policies: rows.map((r) => ({ ...r, snips: Math.round(r.snips * 10000) / 10000, ips: Math.round(r.ips * 10000) / 10000, upliftVsLogged: Math.round((r.snips - logged) * 10000) / 10000 })),
    best: best ? best.name : null,
    regret: best ? Math.round(Math.max(0, best.snips - logged) * 10000) / 10000 : 0,
    recommendation: best && best.snips - logged > 1e-6 ? `Переключение на политику «${best.name}» оценочно даёт +${Math.round((best.snips - logged) * 10000) / 10000} к средней награде.` : 'Текущая (логирующая) политика — не хуже рассмотренных.',
  };
}

module.exports = { evaluate, loggedValue, comparePolicies };
