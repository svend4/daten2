// test/smoke.mjs — реальный E2E: поднимает мок-бэкенд по контракту, спавнит
// MCP-сервер и общается с ним по stdio (JSON-RPC), проверяя все 4 инструмента.
import http from 'http';
import assert from 'assert';
import { spawn } from 'child_process';

const MOCK_PORT = 9911;

// --- мок-бэкенд (единый контракт) ---
const orders = {};
const mock = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  res.setHeader('Content-Type', 'application/json');
  if (u.pathname === '/api/health') return res.end(JSON.stringify({ ok: true, level: 2, stack: 'MockFlask' }));
  if (u.pathname === '/api/products') return res.end(JSON.stringify([
    { id: 1, name: 'Красная роза', price: 1.5, currency: 'EUR', stock: 50, is_featured: true, category_name: 'Розы' },
    { id: 2, name: 'Жёлтый тюльпан', price: 0.8, currency: 'EUR', stock: 100, is_featured: false, category_name: 'Тюльпаны' },
  ]));
  if (u.pathname === '/api/orders' && req.method === 'POST') {
    let b = ''; req.on('data', (c) => (b += c));
    return req.on('end', () => {
      const token = 'mcptoken0000000000000000000000ab';
      orders[token] = { order: { order_number: token, status: 'new', payment_status: 'pending', total_amount: 1.5, customer_name: 'ИИ', phone: '0' }, items: [{ product_name: 'Красная роза', quantity: 1, unit_price: 1.5, line_total: 1.5 }] };
      res.statusCode = 201; res.end(JSON.stringify({ order_number: token, total: 1.5 }));
    });
  }
  const m = u.pathname.match(/^\/api\/orders\/(.+)$/);
  if (m) { const o = orders[m[1]]; if (!o) { res.statusCode = 404; return res.end('{"error":"not found"}'); } return res.end(JSON.stringify(o)); }
  res.statusCode = 404; res.end('{"error":"unknown"}');
});

function rpcClient(child) {
  let buf = '';
  const waiters = new Map();
  child.stdout.on('data', (d) => {
    buf += d.toString();
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      let msg;
      try { msg = JSON.parse(line); } catch { continue; }
      if (msg.id && waiters.has(msg.id)) { waiters.get(msg.id)(msg); waiters.delete(msg.id); }
    }
  });
  const send = (obj) => child.stdin.write(JSON.stringify(obj) + '\n');
  const request = (id, method, params) => new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('timeout ' + method)), 5000);
    waiters.set(id, (m) => { clearTimeout(t); resolve(m); });
    send({ jsonrpc: '2.0', id, method, params });
  });
  return { send, request };
}

async function main() {
  await new Promise((r) => mock.listen(MOCK_PORT, r));

  const child = spawn('node', ['dist/index.js'], {
    env: { ...process.env, BACKEND_URL: `http://localhost:${MOCK_PORT}` },
    stdio: ['pipe', 'pipe', 'inherit'],
  });
  const cli = rpcClient(child);

  // 1) handshake
  const init = await cli.request(1, 'initialize', {
    protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'smoke', version: '1' },
  });
  assert(init.result && init.result.serverInfo.name === 'flower-shop-mcp-server', 'initialize');
  cli.send({ jsonrpc: '2.0', method: 'notifications/initialized' });
  console.log('✓ handshake с MCP-сервером');

  // 2) список инструментов
  const tools = await cli.request(2, 'tools/list', {});
  const names = tools.result.tools.map((t) => t.name).sort();
  assert.deepStrictEqual(names, ['flowershop_create_order', 'flowershop_get_order', 'flowershop_health', 'flowershop_list_products'], 'tools/list');
  console.log('✓ 4 инструмента зарегистрированы:', names.join(', '));

  // 3) health
  const h = await cli.request(3, 'tools/call', { name: 'flowershop_health', arguments: {} });
  assert.strictEqual(h.result.structuredContent.level, 2, 'health level');
  console.log('✓ flowershop_health → уровень 2 (MockFlask)');

  // 4) каталог с фильтром featured_only
  const list = await cli.request(4, 'tools/call', { name: 'flowershop_list_products', arguments: { featured_only: true } });
  assert.strictEqual(list.result.structuredContent.count, 1, 'featured filter');
  assert.strictEqual(list.result.structuredContent.products[0].name, 'Красная роза', 'featured product');
  console.log('✓ flowershop_list_products (featured_only) → 1 товар');

  // 5) оформление заказа
  const order = await cli.request(5, 'tools/call', { name: 'flowershop_create_order', arguments: { name: 'ИИ', items: [{ product_id: 1, quantity: 1 }] } });
  const token = order.result.structuredContent.order_number;
  assert(token && token.length >= 8, 'order token');
  console.log('✓ flowershop_create_order → токен', token.slice(0, 10) + '…');

  // 6) заказ по номеру
  const det = await cli.request(6, 'tools/call', { name: 'flowershop_get_order', arguments: { order_number: token } });
  assert.strictEqual(det.result.structuredContent.order.payment_status, 'pending', 'get_order');
  console.log('✓ flowershop_get_order → заказ найден');

  console.log('\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ✓');
  child.kill();
  mock.close();
}

main().catch((e) => { console.error('✗', e.message); process.exit(1); });
