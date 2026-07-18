// verify.js — верификация провайдера против пакта. Проигрывает каждое взаимодействие
// (с подстановкой захваченных токенов), проверяет статус и типовое совпадение тела.
const matcher = require('./matcher');
const pact = require('./pact');

async function forward(base, method, path, body) {
  const t = Date.now();
  try {
    const r = await fetch(base + path, { method, headers: { 'Content-Type': 'application/json' }, body: ['GET', 'HEAD'].includes(method) ? undefined : JSON.stringify(body || {}), signal: AbortSignal.timeout(Number(process.env.VERIFY_TIMEOUT_MS || 5000)) });
    const text = await r.text(); let b; try { b = text ? JSON.parse(text) : null; } catch { b = text; }
    return { status: r.status, body: b, ms: Date.now() - t };
  } catch (e) { return { status: 0, body: { error: e.message }, ms: Date.now() - t, error: e.message }; }
}

async function verify(base) {
  const captured = {};
  const results = [];
  for (const it of pact.interactions) {
    const path = it.request.path.replace(/\{\{(\w+)\}\}/g, (_, k) => encodeURIComponent(captured[k] ?? 'MISSING'));
    const r = await forward(base, it.request.method, path, it.request.body);
    const statusOk = it.response.status.includes(r.status);
    const bodyRes = it.response.body === 'any' ? { ok: true, mismatches: [] } : matcher.verifyBody(it.response.body, r.body);
    const ok = statusOk && bodyRes.ok;
    if (ok && it.capture) for (const [k, src] of Object.entries(it.capture)) captured[k] = r.body ? r.body[src] : undefined;
    results.push({ id: it.id, description: it.description, ok, status: r.status, statusOk, mismatches: bodyRes.mismatches, ms: r.ms });
  }
  const passed = results.filter((x) => x.ok).length;
  return { provider: base, consumer: pact.consumer, passed, total: results.length, ok: passed === results.length, results };
}

module.exports = { verify };
