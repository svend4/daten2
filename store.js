// store.js — последняя верификация в памяти.
let last = null;
module.exports = { set: (v) => (last = v), get: () => last };
