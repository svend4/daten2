// client.js — клиент единого REST-контракта магазина (для любого языкового порта).
const TIMEOUT = () => AbortSignal.timeout(Number(process.env.ROSETTA_TIMEOUT_MS || 8000));

async function jget(url) {
  const r = await fetch(url, { signal: TIMEOUT() });
  return r.json();
}
async function jpost(url, body) {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), signal: TIMEOUT(),
  });
  return r.json();
}

function client(base) {
  const url = String(base || '').replace(/\/$/, '');
  return {
    url,
    health: () => jget(url + '/api/health'),
    products: () => jget(url + '/api/products'),
    createOrder: (payload) => jpost(url + '/api/orders', payload),
    getOrder: (n) => jget(url + '/api/orders/' + encodeURIComponent(n)),
  };
}
module.exports = { client };
