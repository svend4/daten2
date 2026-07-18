// store.js — последний снимок статусов.
let last = null;
module.exports = { set: (v) => (last = v), get: () => last };
