// runner.js — прогон бенчмарка по всем стекам + рейтинг и метрика эффективности.
const bench = require('./bench');
const round = (n) => (n == null ? null : Math.round(n * 100) / 100);

async function runAll(stacks, opts = {}) {
  const results = [];
  for (const st of stacks) {
    let alive = true;
    try { const r = await fetch(st.url + '/api/health', { signal: AbortSignal.timeout(1500) }); alive = r.ok; }
    catch { alive = false; }
    if (!alive) { results.push({ ...meta(st), alive: false }); continue; }
    const s = await bench.run(st.url, opts);
    // эффективность: успешных запросов на ватт (пропорционально rps/watts)
    const rps_per_watt = st.watts ? round(s.rps / st.watts) : null;
    results.push({ ...meta(st), alive: true, ...s, rps_per_watt });
  }
  return rank(results);
}
const meta = (st) => ({ id: st.id, name: st.name, language: st.language, storage: st.storage, watts: st.watts });

// живые и надёжные вперёд, затем по p95
function rank(results) {
  const sorted = [...results].sort((a, b) => {
    if (a.alive !== b.alive) return a.alive ? -1 : 1;
    return (a.p95 ?? Infinity) - (b.p95 ?? Infinity);
  });
  sorted.forEach((r, i) => (r.rank = r.alive ? i + 1 : null));
  return sorted;
}

module.exports = { runAll, rank };
