// store.js — последний прогон и baseline (список принятых расхождений).
let last = null, baseline = null;
module.exports = {
  setLast: (v) => (last = v), getLast: () => last,
  setBaseline: (v) => (baseline = v), getBaseline: () => baseline,
};
