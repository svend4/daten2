// store.js — последний прогон охоты.
let last = null;
module.exports = { setLast: (v) => (last = v), getLast: () => last };
