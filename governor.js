// governor.js — ГУБЕРНАТОР в контуре с двойником. Каждое предложенное действие
// сперва прогоняется через симуляцию (против базовой линии «ничего не делать») и
// допускается в прод только при БЕЗОПАСНОМ и ВЫГОДНОМ прогнозе. Иначе — блок или
// эскалация человеку. Если действие небезопасно/невыгодно — губернатор ищет среди
// альтернатив безопасную выгодную и рекомендует её.
const sim = require('./sim');
const predicates = require('./predicates');

const NOOP = { type: 'noop' };

function generateAlternatives(action, state) {
  const alts = [];
  if (action && action.type === 'reorder') {
    for (const f of [0.5, 0.25]) { const q = Math.round((action.quantity || 0) * f); if (q > 0) alts.push({ type: 'reorder', productId: action.productId, quantity: q }); }
  } else if (action && action.type === 'reprice') {
    const p = state.products.find((x) => x.id === action.productId);
    if (p) alts.push({ type: 'reprice', productId: action.productId, newPrice: Math.round((p.price + Number(action.newPrice)) / 2) });
  }
  alts.push(NOOP);
  return alts;
}

function evaluate(state, action, opts = {}) {
  const cfg = { ...predicates.DEFAULTS, ...(opts.config || {}) };
  const steps = opts.steps || 10;
  const noop = sim.rollForward(state, NOOP, { steps });
  const simmed = sim.rollForward(state, action, { steps });
  const violations = predicates.evaluate(simmed, noop, cfg);
  const hard = violations.filter((v) => v.severity === 'hard');
  const soft = violations.filter((v) => v.severity === 'soft');
  const isBeneficial = predicates.beneficial(simmed, noop, cfg);

  let decision, reason;
  if (hard.length) { decision = 'block'; reason = 'жёсткое нарушение: ' + hard.map((v) => v.code).join(', '); }
  else if (!isBeneficial) { decision = 'block'; reason = 'прогноз не лучше бездействия'; }
  else if (soft.length) { decision = 'escalate'; reason = 'безопасно и выгодно, но есть мягкий риск: ' + soft.map((v) => v.code).join(', '); }
  else { decision = 'admit'; reason = 'прогноз безопасен и выгоден'; }

  // поиск безопасной выгодной альтернативы (для рекомендации при block/escalate)
  const cands = (opts.alternatives || generateAlternatives(action, state));
  const evaluated = cands.map((a) => { const s = sim.rollForward(state, a, { steps }); return { action: a, sim: s, hard: predicates.evaluate(s, noop, cfg).filter((v) => v.severity === 'hard').length, beneficial: predicates.beneficial(s, noop, cfg) }; });
  const safe = evaluated.filter((e) => e.hard === 0 && e.beneficial).sort((a, b) => b.sim.profit - a.sim.profit);
  const best = safe[0];
  const recommendation = (decision !== 'admit' && best && JSON.stringify(best.action) !== JSON.stringify(action)) ? { action: best.action, profit: best.sim.profit } : null;

  return { decision, reason, action, violations, simulated: simmed, baseline: noop, uplift: Math.round((simmed.profit - noop.profit) * 100) / 100, recommendation };
}

module.exports = { evaluate, generateAlternatives };
