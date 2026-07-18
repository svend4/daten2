// bench.js — ядро бенчмарка. Нагружает один бэкенд по эндпоинту контракта и
// собирает латентность (p50/p95/p99/avg), пропускную способность и надёжность.
// По умолчанию бьёт только по чтению (/api/products, /api/health) — без побочных
// эффектов, безопасно для наблюдения за живым магазином.

const round = (n) => Math.round(n * 100) / 100;

function percentile(sorted, p) {
  if (!sorted.length) return null;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[idx];
}

function summarize(latencies, ok, failed, wallMs) {
  const sorted = [...latencies].sort((a, b) => a - b);
  const total = ok + failed;
  return {
    requests: total,
    ok,
    failed,
    success_ratio: total ? round(ok / total) : 0,
    throughput_rps: wallMs > 0 ? round((ok / wallMs) * 1000) : 0,
    latency_ms: {
      min: sorted.length ? round(sorted[0]) : null,
      p50: round(percentile(sorted, 50)),
      p95: round(percentile(sorted, 95)),
      p99: round(percentile(sorted, 99)),
      max: sorted.length ? round(sorted[sorted.length - 1]) : null,
      avg: sorted.length ? round(sorted.reduce((a, b) => a + b, 0) / sorted.length) : null,
    },
    wall_ms: wallMs,
  };
}

// Нагрузка одного URL: `requests` запросов при параллелизме `concurrency`.
async function benchOne(url, opts = {}, fetchImpl = fetch, clock = Date.now) {
  const { path = '/api/products', method = 'GET', body = null, requests = 100, concurrency = 10, timeoutMs = 5000 } = opts;
  const latencies = [];
  let ok = 0, failed = 0, i = 0;
  const t0 = clock();
  async function worker() {
    while (true) {
      const idx = i++;
      if (idx >= requests) break;
      const s = clock();
      try {
        const r = await fetchImpl(url + path, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: body ? JSON.stringify(body) : undefined,
          signal: AbortSignal.timeout(timeoutMs),
        });
        await r.text();
        const dt = clock() - s;
        if (r.ok) { ok++; latencies.push(dt); } else failed++;
      } catch { failed++; }
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, concurrency) }, () => worker()));
  return summarize(latencies, ok, failed, clock() - t0);
}

// Бенчмарк всех уровней (последовательно — чтобы не мешать друг другу на общем железе).
async function benchAll(levels, opts = {}, fetchImpl = fetch, clock = Date.now) {
  const results = [];
  for (const lv of levels) {
    let live = true;
    try { const r = await fetchImpl(lv.url + '/api/health', { signal: AbortSignal.timeout(1500) }); live = r.ok; }
    catch { live = false; }
    if (!live) { results.push({ id: lv.id, name: lv.name, url: lv.url, alive: false, ...summarize([], 0, 0, 0) }); continue; }
    const s = await benchOne(lv.url, opts, fetchImpl, clock);
    results.push({ id: lv.id, name: lv.name, url: lv.url, alive: true, ...s });
  }
  return results;
}

// Рейтинг: живые и надёжные вперёд, затем по p95, затем по пропускной способности.
function rank(results) {
  return [...results].sort((a, b) => {
    if (a.alive !== b.alive) return a.alive ? -1 : 1;
    if (b.success_ratio !== a.success_ratio) return b.success_ratio - a.success_ratio;
    const ap = a.latency_ms.p95 ?? Infinity, bp = b.latency_ms.p95 ?? Infinity;
    if (ap !== bp) return ap - bp;
    return b.throughput_rps - a.throughput_rps;
  });
}

module.exports = { benchOne, benchAll, summarize, percentile, rank };
