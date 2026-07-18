// chaos.js — инъектор сбоев: перед проксированием применяет к цели её fault-состояние.
// errorRate детерминирован (каждый N-й запрос), чтобы chaos-эксперименты были воспроизводимы.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function forward(t, method, path, body) {
  const f = t.fault || {}; const start = Date.now();
  if (f.down) return { ok: false, status: 503, ms: Date.now() - start, injected: 'down' };
  if (f.errorRate > 0) {
    t._c = (t._c || 0) + 1;
    const every = Math.max(1, Math.round(1 / f.errorRate));
    if (t._c % every === 0) { if (f.latencyMs) await sleep(f.latencyMs); return { ok: false, status: 500, ms: Date.now() - start, injected: 'error' }; }
  }
  if (f.latencyMs) await sleep(f.latencyMs);
  try {
    const r = await fetch(t.url + path, { method, headers: { 'Content-Type': 'application/json' }, body: ['GET', 'HEAD'].includes(method) ? undefined : JSON.stringify(body || {}), signal: AbortSignal.timeout(Number(process.env.CHAOS_TIMEOUT_MS || 4000)) });
    const text = await r.text(); let b; try { b = text ? JSON.parse(text) : null; } catch { b = text; }
    return { ok: r.ok, status: r.status, body: b, ms: Date.now() - start };
  } catch (e) { return { ok: false, status: 502, ms: Date.now() - start, error: e.message }; }
}

module.exports = { forward };
