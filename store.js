// store.js — последний прогон и baseline (для регрессий).
let last = null, baseline = null;
module.exports = {
  setLast: (v) => (last = v), getLast: () => last,
  setBaseline: (v) => (baseline = v), getBaseline: () => baseline,
};
