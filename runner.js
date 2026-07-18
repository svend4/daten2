// runner.js — «живой» режим двойника: прогоняет симуляцию против настоящего
// бэкенда, оформляя реальные заказы через контракт. Так двойник создаёт живой
// трафик — им кормятся роутер, наблюдаемость и управляющий (замкнутый контур).
const contract = require('./contract');
const sim = require('./sim');

async function runLive(opts = {}) {
  const catalog = await contract.listProducts();
  // в живом режиме покупают по реальным ценам (множитель только для offline what-if)
  const result = sim.simulate(catalog, { ...opts, priceMultiplier: 1 });

  const placed = [];
  const failures = [];
  let backendRevenue = 0;
  const limit = Math.min(result.orders.length, opts.maxOrders || 500);
  for (let i = 0; i < limit; i++) {
    const o = result.orders[i];
    try {
      const res = await contract.createOrder({
        name: `twin-${o.persona}-${i}`,
        items: [{ product_id: o.product_id, quantity: o.quantity }],
      });
      placed.push({ order_number: res.order_number, total: res.total, persona: o.persona });
      backendRevenue += Number(res.total) || 0;
    } catch (e) {
      failures.push({ product_id: o.product_id, error: String(e.message) });
    }
  }

  return {
    mode: 'live',
    params: result.params,
    totals: result.totals,
    placed_orders: placed.length,
    failed_orders: failures.length,
    backend_revenue: Math.round(backendRevenue * 100) / 100,
    order_numbers: placed.map((p) => p.order_number),
    failures: failures.slice(0, 10),
    unitsByProduct: result.unitsByProduct,
    bySegment: result.bySegment,
    series: result.series,
  };
}

module.exports = { runLive };
