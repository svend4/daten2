// contract-test/mock-backend.mjs — эталонный контракт-совместимый бэкенд.
// Нужен, чтобы прогонять contract-test в CI без развёртывания реальных уровней,
// и как референс того, что должен реализовать каждый уровень.
import http from 'http';
import { randomUUID } from 'crypto';

const products = [
  { id: 1, name: 'Красная роза', slug: 'red-rose', description: '…', price: 1.5, currency: 'EUR', image: 'images/rose.jpg', sku: 'ROSE-RED-01', stock: 50, is_featured: true, category_name: 'Розы' },
  { id: 2, name: 'Жёлтый тюльпан', slug: 'yellow-tulip', description: '…', price: 0.8, currency: 'EUR', image: 'images/tulip.jpg', sku: 'TULIP-YEL-01', stock: 100, is_featured: false, category_name: 'Тюльпаны' },
];
const orders = {};

function send(res, code, obj) {
  res.statusCode = code;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(obj));
}
async function readBody(req) {
  let b = '';
  for await (const c of req) b += c;
  try { return JSON.parse(b || '{}'); } catch { return {}; }
}

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  if (u.pathname === '/api/health') return send(res, 200, { ok: true, level: 0, stack: 'ReferenceMock' });
  if (u.pathname === '/api/products') return send(res, 200, products);

  if (u.pathname === '/api/orders' && req.method === 'POST') {
    const body = await readBody(req);
    const items = Array.isArray(body.items) ? body.items : [];
    if (!body.name || items.length === 0) return send(res, 400, { error: 'name/items required' });
    let subtotal = 0;
    const lines = [];
    for (const it of items) {
      const p = products.find((x) => x.id === Number(it.product_id));
      if (!p) continue;
      const qty = Number(it.quantity) || 1;
      const line = p.price * qty;
      subtotal += line;
      lines.push({ product_name: p.name, quantity: qty, unit_price: p.price, line_total: line });
    }
    if (!lines.length) return send(res, 400, { error: 'no valid items' });
    const token = randomUUID().replace(/-/g, '');
    orders[token] = {
      order: { order_number: token, status: 'new', payment_status: 'pending', total_amount: subtotal, customer_name: body.name, phone: body.phone || '' },
      items: lines,
    };
    return send(res, 201, { order_number: token, total: subtotal });
  }

  const m = u.pathname.match(/^\/api\/orders\/(.+)$/);
  if (m && req.method === 'GET') {
    const o = orders[m[1]];
    return o ? send(res, 200, o) : send(res, 404, { error: 'not found' });
  }
  send(res, 404, { error: 'unknown endpoint' });
});

const PORT = process.env.PORT || 8100;
server.listen(PORT, () => console.log(`reference mock backend on :${PORT}`));
