// analytics.js — детерминированное ядро управляющего.
// Из временного ряда снимков каталога выводит: скорость продаж, прогноз спроса и
// исчерпания склада, точку и объём дозаказа, подсказки по цене, аномалии.
// Спрос выводится из просадки остатков между снимками — работает поверх контракта,
// не требуя доступа к списку заказов.

const DAY = 86_400_000; // мс в сутках

const CFG = {
  leadTimeDays: Number(process.env.LEAD_TIME_DAYS || 3),   // срок поставки
  safetyDays: Number(process.env.SAFETY_DAYS || 2),        // страховой запас
  coverageDays: Number(process.env.COVERAGE_DAYS || 14),   // на сколько дней дозаказывать
  zThreshold: Number(process.env.ANOMALY_Z || 2.5),        // порог z-оценки аномалии
  minSamples: Number(process.env.MIN_SAMPLES || 4),        // минимум интервалов для статистики
};

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
function std(xs) {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(mean(xs.map((x) => (x - m) ** 2)));
}
const round2 = (n) => Math.round(n * 100) / 100;

// Ряд интервалов по одному товару: продажи (просадка остатка) и дозавозы.
function intervals(snapshots, productId) {
  const rows = [];
  for (let i = 1; i < snapshots.length; i++) {
    const a = snapshots[i - 1].products.find((p) => p.id === productId);
    const b = snapshots[i].products.find((p) => p.id === productId);
    const dt = snapshots[i].t - snapshots[i - 1].t;
    if (!a || !b || dt <= 0) continue;
    const delta = a.stock - b.stock;                 // >0 продажи, <0 дозавоз
    const sold = Math.max(0, delta);
    rows.push({
      dt,
      sold,
      restock: delta < 0 ? -delta : 0,
      dailyRate: (sold / dt) * DAY,                  // ед./сутки
      priceChange: b.price - a.price,
    });
  }
  return rows;
}

function analyzeProduct(snapshots, product) {
  const rows = intervals(snapshots, product.id);
  const rates = rows.filter((r) => r.restock === 0).map((r) => r.dailyRate);
  const dailyRate = round2(mean(rates));             // средний спрос, ед./сутки
  const stock = product.stock;

  const daysToStockout = dailyRate > 0 ? round2(stock / dailyRate) : null; // null = не расходуется
  const reorderPoint = round2(dailyRate * (CFG.leadTimeDays + CFG.safetyDays));
  const needsReorder = dailyRate > 0 && stock <= reorderPoint;
  const target = dailyRate * (CFG.leadTimeDays + CFG.coverageDays);
  const reorderQty = needsReorder ? Math.max(0, Math.ceil(target - stock)) : 0;

  // Подсказка по цене
  let priceAction = 'hold';
  let priceReason = 'спрос и запас сбалансированы';
  let suggestedPrice = product.price;
  if (dailyRate > 0 && daysToStockout !== null && daysToStockout < CFG.leadTimeDays) {
    priceAction = 'raise';
    suggestedPrice = round2(product.price * 1.1);
    priceReason = `закончится за ${daysToStockout} дн. (< срока поставки ${CFG.leadTimeDays}) — спрос выше поставок`;
  } else if (dailyRate === 0 && rows.length >= CFG.minSamples && stock > 0) {
    priceAction = 'discount';
    suggestedPrice = round2(product.price * 0.9);
    priceReason = `нет продаж за ${rows.length} интервалов при остатке ${stock} — залёживается`;
  } else if (product.is_featured && dailyRate > 0) {
    priceReason = 'рекомендуемый и продаётся — удерживать цену';
  }

  // Аномалии
  const anomalies = [];
  const last = rows[rows.length - 1];
  if (rates.length >= CFG.minSamples) {
    const s = std(rates);
    if (s > 0 && last && last.restock === 0) {
      const z = (last.dailyRate - mean(rates)) / s;
      if (Math.abs(z) >= CFG.zThreshold) {
        anomalies.push({
          type: last.dailyRate > mean(rates) ? 'spike' : 'drop',
          metric: 'sales',
          z: round2(z),
          detail: `спрос ${round2(last.dailyRate)} ед./сут при среднем ${dailyRate} (z=${round2(z)})`,
        });
      }
    }
  }
  if (last && Math.abs(last.priceChange) > 1e-9) {
    anomalies.push({ type: 'price-change', metric: 'price', detail: `цена изменилась на ${round2(last.priceChange)}` });
  }
  const lastRestock = rows.filter((r) => r.restock > 0).pop();

  return {
    id: product.id,
    name: product.name,
    price: product.price,
    stock,
    is_featured: product.is_featured,
    dailyRate,
    daysToStockout,
    reorderPoint,
    needsReorder,
    reorderQty,
    price_suggestion: { action: priceAction, from: product.price, to: suggestedPrice, reason: priceReason },
    anomalies,
    lastRestock: lastRestock ? lastRestock.restock : 0,
    samples: rows.length,
  };
}

function report(snapshots) {
  const latest = snapshots[snapshots.length - 1];
  if (!latest) return { generatedFrom: 0, products: [], reorders: [], anomalies: [], summary: 'Нет данных: снимков ещё не собрано.' };
  const products = latest.products.map((p) => analyzeProduct(snapshots, p));
  const reorders = products.filter((p) => p.needsReorder)
    .map((p) => ({ id: p.id, name: p.name, stock: p.stock, reorderPoint: p.reorderPoint, quantity: p.reorderQty, dailyRate: p.dailyRate }));
  const anomalies = products.flatMap((p) => p.anomalies.map((a) => ({ product: p.name, id: p.id, ...a })));
  const price = products.filter((p) => p.price_suggestion.action !== 'hold')
    .map((p) => ({ name: p.name, ...p.price_suggestion }));

  const parts = [];
  parts.push(`Снимков в анализе: ${snapshots.length}.`);
  if (reorders.length) parts.push(`К дозаказу: ${reorders.map((r) => `${r.name} (+${r.quantity})`).join(', ')}.`);
  else parts.push('Дозаказ не требуется.');
  if (anomalies.length) parts.push(`Аномалии: ${anomalies.map((a) => `${a.product}/${a.type}`).join(', ')}.`);
  if (price.length) parts.push(`Цены: ${price.map((p) => `${p.name} ${p.action}`).join(', ')}.`);

  return { generatedFrom: snapshots.length, products, reorders, anomalies, price_suggestions: price, summary: parts.join(' ') };
}

module.exports = { report, analyzeProduct, intervals, CFG };
