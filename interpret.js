// interpret.js — детерминированная сводка по бенчмарку (фолбэк без ключа).
const store = require('./store');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const run = store.get();
  if (!run) return { reply: 'Бенчмарк ещё не запускался — сгенерируйте отчёт.', engine: 'rules' };
  const alive = run.results.filter((r) => r.alive);
  if (!alive.length) return { reply: 'Ни один стек не ответил.', engine: 'rules' };

  if (/эффект|ватт|энерг|green|зелён/.test(low)) {
    const g = [...alive].filter((r) => r.rps_per_watt != null).sort((a, b) => b.rps_per_watt - a.rps_per_watt);
    return { reply: 'Эффективность (rps/Вт):\n' + g.map((r) => `• ${r.name}: ${r.rps_per_watt}`).join('\n'), engine: 'rules' };
  }
  if (/медлен|худш|slow/.test(low)) {
    const s = [...alive].reverse();
    return { reply: 'От медленных к быстрым (p95):\n' + s.map((r) => `• ${r.name}: ${r.p95} мс`).join('\n'), engine: 'rules' };
  }
  const w = alive[0];
  return { reply: `Самый быстрый стек — «${w.name}» (p95 ${w.p95} мс, ${w.rps} rps). Всего в отчёте ${run.results.length} стеков, живых ${alive.length}.`, engine: 'rules' };
}
module.exports = { ask };
