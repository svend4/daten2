// load.js — генератор нагрузки и метрик (success rate, p50/p95).
async function run(sutFn, { requests = 40, concurrency = 8 } = {}) {
  const lat = []; let ok = 0, fail = 0, i = 0;
  async function worker() { while (true) { const idx = i++; if (idx >= requests) break; const r = await sutFn(); if (r.ok) { ok++; lat.push(r.ms); } else fail++; } }
  const t0 = Date.now();
  await Promise.all(Array.from({ length: Math.max(1, concurrency) }, () => worker()));
  const wall = Date.now() - t0;
  lat.sort((a, b) => a - b);
  const pct = (p) => (lat.length ? lat[Math.min(lat.length - 1, Math.max(0, Math.ceil((p / 100) * lat.length) - 1))] : null);
  return { requests, ok, fail, successRate: requests ? Math.round((ok / requests) * 1000) / 1000 : 0, p50: pct(50), p95: pct(95), wallMs: wall };
}
module.exports = { run };
