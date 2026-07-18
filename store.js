// store.js — последний план.
let last = null;
module.exports = { setLast: (v) => (last = v), getLast: () => last };
