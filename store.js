// store.js — последний прогон и его метаданные.
let last = null;
module.exports = { set: (v) => (last = v), get: () => last };
