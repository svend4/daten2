// store.js — последний chaos-прогон в памяти.
let last = null;
module.exports = { set: (v) => (last = v), get: () => last };
