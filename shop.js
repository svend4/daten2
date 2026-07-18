// shop.js — клиент единого контракта магазина (любой уровень или роутер).
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

const listProducts = () => req('/api/products');
const createOrder = (payload) => req('/api/orders', { method: 'POST', body: JSON.stringify(payload) });
const getOrder = (orderNumber) => req('/api/orders/' + encodeURIComponent(orderNumber));

// Клиентские фильтры (контракт без query-параметров)
function filterProducts(products, { search, featured_only, max_price, in_stock } = {}) {
  let out = products;
  if (search) { const q = String(search).toLowerCase(); out = out.filter((p) => p.name.toLowerCase().includes(q)); }
  if (featured_only) out = out.filter((p) => p.is_featured);
  if (typeof max_price === 'number') out = out.filter((p) => Number(p.price) <= max_price);
  if (in_stock) out = out.filter((p) => p.stock > 0);
  return out;
}

module.exports = { BACKEND_URL, listProducts, createOrder, getOrder, filterProducts };
