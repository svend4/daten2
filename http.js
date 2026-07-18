// http.js — HTTP-хелперы, привязанные к базовому URL цели эвала.
function client(base) {
  const url = String(base || '').replace(/\/$/, '');
  async function raw(path, init) {
    const r = await fetch(url + path, { ...init, headers: { 'Content-Type': 'application/json', ...(init && init.headers) }, signal: AbortSignal.timeout(Number(process.env.EVAL_TIMEOUT_MS || 5000)) });
    const text = await r.text();
    let body; try { body = text ? JSON.parse(text) : null; } catch { body = text; }
    return { status: r.status, ok: r.ok, body, headers: r.headers };
  }
  return {
    url,
    get: (p) => raw(p),
    post: (p, b) => raw(p, { method: 'POST', body: JSON.stringify(b || {}) }),
  };
}
module.exports = { client };
