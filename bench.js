// bench.js — нагрузочный замер одного стека: латентность (p50/p95/p99), пропускная
// способность (rps), надёжность. По умолчанию — только чтение (без побочек).
const round = (n) => (n == null ? null : Math.round(n * 100) / 100);

function summarize(latencies, ok, failed, wallMs) {
  const s = [...latencies].sort((a, b) => a - b);
  const pct = (p) => (s.length ? s[Math.min(s.length - 1, Math.max(0, Math.ceil((p / 100) * s.length) - 1))] : null);
  const total = ok + failed;
  return {
    requests: total, ok, failed,
    success_ratio: total ? round(ok / total) : 0,
    rps: wallMs > 0 ? round((ok / wallMs) * 1000) : 0,
    p50: round(pct(50)), p95: round(pct(95)), p99: round(pct(99)),
    min: s.length ? round(s[0]) : null, max: s.length ? round(s[s.length - 1]) : null,
    avg: s.length ? round(s.reduce((a, b) => a + b, 0) / s.length) : null,
  };
}

async function run(url, opts = {}, fetchImpl = fetch, clock = Date.now) {
  const { path = '/api/products', requests = 100, concurrency = 10, timeoutMs = 5000, warmup = 5 } = opts;
  // прогрев (не учитывается в метриках)
  for (let i = 0; i < warmup; i++) { try { await fetchImpl(url + path, { signal: AbortSignal.timeout(timeoutMs) }); } catch { /* ignore */ } }
  const lat = []; let ok = 0, failed = 0, i = 0;
  const t0 = clock();
  async function worker() {
    while (true) {
      const idx = i++; if (idx >= requests) break;
      const s = clock();
      try { const r = await fetchImpl(url + path, { signal: AbortSignal.timeout(timeoutMs) }); await r.text(); if (r.ok) { ok++; lat.push(clock() - s); } else failed++; }
      catch { failed++; }
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, concurrency) }, () => worker()));
  return summarize(lat, ok, failed, clock() - t0);
}

module.exports = { run, summarize };
