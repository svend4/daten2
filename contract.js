// contract.js — клиент единого контракта (для защищённого оформления заказа).
const BACKEND_URL = (process.env.BACKEND_URL || 'http://localhost:8080').replace(/\/$/, '');

async function req(path, init) {
  const r = await fetch(BACKEND_URL + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init && init.headers) },
  });
  const text = await r.text();
  let body;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!r.ok) throw new Error(body && body.error ? body.error : `HTTP ${r.status}`);
  return body;
}

const createOrder = (payload) => req('/api/orders', { method: 'POST', body: JSON.stringify(payload) });

module.exports = { BACKEND_URL, createOrder };
