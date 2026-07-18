// store.js — состояние магазина-двойника + журнал решений губернатора.
const sim = require('./sim');
let state = sim.defaultState();
const log = [];
module.exports = {
  getState: () => state,
  setState: (s) => (state = s),
  reset: () => (state = sim.defaultState()),
  record: (entry) => { log.push(entry); if (log.length > 500) log.shift(); return entry; },
  log: () => log.slice(-200),
  stats: () => { const m = {}; for (const e of log) m[e.decision] = (m[e.decision] || 0) + 1; return { total: log.length, ...m }; },
};
