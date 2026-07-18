// monitor.js — опрос /api/health всех сервисов, агрегация по категориям.
async function poll(service, fetchImpl = fetch) {
  const t = Date.now();
  try {
    const r = await fetchImpl(service.url + '/api/health', { signal: AbortSignal.timeout(Number(process.env.PORTAL_TIMEOUT_MS || 2000)) });
    const text = await r.text(); let body; try { body = text ? JSON.parse(text) : null; } catch { body = null; }
    return { id: service.id, up: r.ok, engine: (body && body.engine) || null, ms: Date.now() - t };
  } catch (e) { return { id: service.id, up: false, engine: null, ms: Date.now() - t, error: e.message }; }
}

async function pollAll(services, fetchImpl = fetch) {
  const statuses = await Promise.all(services.map((s) => poll(s, fetchImpl)));
  const byId = Object.fromEntries(statuses.map((s) => [s.id, s]));
  const merged = services.map((s) => ({ ...s, ...byId[s.id] }));
  const up = merged.filter((s) => s.up).length;
  const byCat = {};
  for (const s of merged) { const c = (byCat[s.cat] = byCat[s.cat] || { total: 0, up: 0 }); c.total++; if (s.up) c.up++; }
  return { at: new Date().toISOString(), total: merged.length, up, down: merged.length - up, byCat, services: merged };
}

module.exports = { poll, pollAll };
