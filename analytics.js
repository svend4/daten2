// analytics.js — ядро анализа (как у ИИ-управляющего): из ряда снимков каталога
// выводит спрос, точку/объём дозаказа, подсказку по цене и аномалии. На этих
// выводах автономная петля строит предлагаемые действия.
const CFG = {
  leadTimeDays: Number(process.env.LEAD_TIME_DAYS || 3),
  safetyDays: Number(process.env.SAFETY_DAYS || 2),
  coverageDays: Number(process.env.COVERAGE_DAYS || 14),
  zThreshold: Number(process.env.ANOMALY_Z || 2.5),
  minSamples: Number(process.env.MIN_SAMPLES || 4),
};
const DAY = 86_400_000;
const round2 = (n) => Math.round(n * 100) / 100;
const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
const std = (xs) => (xs.length < 2 ? 0 : Math.sqrt(mean(xs.map((x) => (x - mean(xs)) ** 2))));

function intervals(snapshots, id) {
  const rows = [];
  for (let i = 1; i < snapshots.length; i++) {
    const a = snapshots[i - 1].products.find((p) => p.id === id);
    const b = snapshots[i].products.find((p) => p.id === id);
    const dt = snapshots[i].t - snapshots[i - 1].t;
    if (!a || !b || dt <= 0) continue;
    const delta = a.stock - b.stock;
    rows.push({ dailyRate: (Math.max(0, delta) / dt) * DAY, restock: delta < 0 ? -delta : 0, priceChange: b.price - a.price });
  }
  return rows;
}

function analyzeProduct(snapshots, product) {
  const rows = intervals(snapshots, product.id);
  const rates = rows.filter((r) => r.restock === 0).map((r) => r.dailyRate);
  const dailyRate = round2(mean(rates));
  const stock = product.stock;
  const daysToStockout = dailyRate > 0 ? round2(stock / dailyRate) : null;
  const reorderPoint = round2(dailyRate * (CFG.leadTimeDays + CFG.safetyDays));
  const needsReorder = dailyRate > 0 && stock <= reorderPoint;
  const target = dailyRate * (CFG.leadTimeDays + CFG.coverageDays);
  const reorderQty = needsReorder ? Math.max(0, Math.ceil(target - stock)) : 0;

  let priceAction = 'hold', suggestedPrice = product.price;
  if (dailyRate > 0 && daysToStockout !== null && daysToStockout < CFG.leadTimeDays) { priceAction = 'raise'; suggestedPrice = round2(product.price * 1.1); }
  else if (dailyRate === 0 && rows.length >= CFG.minSamples && stock > 0) { priceAction = 'discount'; suggestedPrice = round2(product.price * 0.9); }

  const anomalies = [];
  const last = rows[rows.length - 1];
  if (rates.length >= CFG.minSamples && last && last.restock === 0) {
    const s = std(rates);
    if (s > 0) { const z = (last.dailyRate - mean(rates)) / s; if (Math.abs(z) >= CFG.zThreshold) anomalies.push({ type: last.dailyRate > mean(rates) ? 'spike' : 'drop', z: round2(z) }); }
  }

  return { id: product.id, name: product.name, price: product.price, stock, dailyRate, daysToStockout, reorderPoint, needsReorder, reorderQty, price_suggestion: { action: priceAction, from: product.price, to: suggestedPrice }, anomalies };
}

function report(snapshots) {
  const latest = snapshots[snapshots.length - 1];
  if (!latest) return { generatedFrom: 0, products: [] };
  return { generatedFrom: snapshots.length, products: latest.products.map((p) => analyzeProduct(snapshots, p)) };
}

module.exports = { report, analyzeProduct, CFG };
