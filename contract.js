// contract.js — ЖИВАЯ проверка соответствия контракту. Плагин допускается в
// каталог, только если реально реализует контракт: health/products/create/get.
// Это supply-side гейт: заявке в манифесте не верим — проверяем поведением.
const TIMEOUT = () => AbortSignal.timeout(Number(process.env.MARKET_TIMEOUT_MS || 6000));
const getJson = async (u) => (await fetch(u, { signal: TIMEOUT() })).json();
const postJson = async (u, b) => (await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b), signal: TIMEOUT() })).json();
const pick = (o, ...k) => { for (const x of k) if (o && o[x] != null) return o[x]; return undefined; };

async function probe(base) {
  const url = String(base).replace(/\/$/, '');
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok: !!ok, detail: detail || '' });

  // health — если недоступен, дальше нет смысла
  try { const h = await getJson(url + '/api/health'); add('health', h && (h.ok === true || h.status === 'ok' || h.healthy === true || h.status === 'healthy'), 'GET /api/health'); }
  catch (e) { add('health', false, 'недоступен: ' + e.message); return finalize(checks); }

  // products
  let products = [];
  try { const p = await getJson(url + '/api/products'); products = Array.isArray(p) ? p : (p.products || p.items || []); add('products', products.length > 0 && products.every((x) => pick(x, 'name', 'title') != null && pick(x, 'price', 'unit_price') != null), `${products.length} товаров с именем и ценой`); }
  catch (e) { add('products', false, e.message); }

  // create order
  let onum = null, total = null;
  try {
    const pid = (products[0] && pick(products[0], 'id')) != null ? pick(products[0], 'id') : 1;
    const o = await postJson(url + '/api/orders', { items: [{ product_id: pid, quantity: 2 }], customer: { name: 'Marketplace', email: 'm@example.com', phone: '+10000000000', address: 'x' } });
    onum = pick(o, 'order_number', 'orderNumber', 'number');
    total = Number(pick(o, 'total', 'total_amount', 'sum'));
    add('create-order', onum != null && !Number.isNaN(total), onum ? ('токен ' + String(onum).slice(0, 14) + ', сумма ' + total) : 'нет order_number/total');
  } catch (e) { add('create-order', false, e.message); }

  // get order по токену
  if (onum != null) {
    try { const g = await getJson(url + '/api/orders/' + encodeURIComponent(onum)); const gt = Number(pick(g, 'total', 'total_amount', 'sum')); add('get-order', pick(g, 'status', 'state') != null && Math.abs(gt - total) < 0.01, 'статус есть, сумма совпала'); }
    catch (e) { add('get-order', false, e.message); }
  } else add('get-order', false, 'нет токена для проверки');

  return finalize(checks);
}

function finalize(checks) {
  const passed = checks.filter((c) => c.ok).length;
  return { checks, passed, total: checks.length, score: Math.round((passed / Math.max(1, checks.length)) * 100) / 100, certified: checks.length >= 4 && checks.every((c) => c.ok) };
}

module.exports = { probe };
