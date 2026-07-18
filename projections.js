// projections.js — read-models как СВЁРТКА событий (event sourcing).
// build(events) детерминированно восстанавливает состояние из журнала — поэтому
// проекции всегда можно пересобрать (rebuild) из источника истины.
const round2 = (n) => Math.round(n * 100) / 100;

function empty() {
  return { eventCount: 0, byType: {}, orders: { count: 0, revenue: 0 }, stock: {}, priceHistory: [], lastSeq: 0 };
}

function apply(s, e) {
  s.eventCount++;
  s.byType[e.type] = (s.byType[e.type] || 0) + 1;
  s.lastSeq = e.seq;
  if (e.type === 'OrderPlaced') { s.orders.count++; s.orders.revenue = round2(s.orders.revenue + (Number(e.payload.total) || 0)); }
  else if (e.type === 'StockChanged') { s.stock[e.payload.product_id] = e.payload.to; }
  else if (e.type === 'PriceChanged') { s.priceHistory.push({ product_id: e.payload.product_id, name: e.payload.name, from: e.payload.from, to: e.payload.to, seq: e.seq }); if (s.priceHistory.length > 100) s.priceHistory = s.priceHistory.slice(-100); }
  return s;
}

const build = (events) => events.reduce(apply, empty());

module.exports = { empty, apply, build };
