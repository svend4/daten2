// policies.js — целевые политики как РАСПРЕДЕЛЕНИЯ π(action | context, actions).
// Возвращают map id→вероятность (сумма = 1). Детерминированная политика кладёт 1.0
// на выбранное действие; стохастическая (uniform) — равномерно. Такой вид годится
// и для детерминированных, и для случайных политик в оценщике IPS.
const attr = (a, k, d) => (a && a[k] != null ? Number(a[k]) : d);

function point(actions, id) { const d = {}; for (const a of actions) d[a.id] = a.id === id ? 1 : 0; return d; }
function argmin(actions, f) { return actions.reduce((b, a) => (f(a) < f(b) ? a : b)).id; }
function argmax(actions, f) { return actions.reduce((b, a) => (f(a) > f(b) ? a : b)).id; }

const REGISTRY = {
  cheapest: (_ctx, actions) => point(actions, argmin(actions, (a) => attr(a, 'cost', Infinity))),
  fastest: (_ctx, actions) => point(actions, argmin(actions, (a) => attr(a, 'latency', Infinity))),
  'greedy-reward': (_ctx, actions) => point(actions, argmax(actions, (a) => attr(a, 'predicted', -Infinity))),
  'most-reliable': (_ctx, actions) => point(actions, argmax(actions, (a) => attr(a, 'reliability', -Infinity))),
  uniform: (_ctx, actions) => { const d = {}; for (const a of actions) d[a.id] = 1 / actions.length; return d; },
};

const names = () => Object.keys(REGISTRY);
function prob(name, ctx, actions) { const f = REGISTRY[name]; if (!f) throw new Error('нет политики: ' + name); return f(ctx, actions); }

module.exports = { REGISTRY, names, prob, attr };
