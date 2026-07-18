// sim.js — ядро цифрового двойника. По каталогу и сегментам моделирует поток
// посетителей во времени: приход → просмотр → решение (с реакцией спроса на цену)
// → заказ. Детерминированно при заданном seed. Чистая функция — без сети и побочек.
const { makeRng, weighted } = require('./rng');
const clamp01 = (n) => Math.max(0, Math.min(1, n));
const round2 = (n) => Math.round(n * 100) / 100;

// интерес сегмента к товару по корню названия
function affinityOf(persona, name) {
  const n = String(name || '').toLowerCase();
  let best = 0.1; // базовый интерес к незнакомому
  for (const root of Object.keys(persona.affinity)) if (n.includes(root)) best = Math.max(best, persona.affinity[root]);
  return best;
}

// один посетитель принимает решение о покупке
function decide(persona, catalog, priceMultiplier, rng) {
  // эффективные цены (what-if наценка/скидка — только в модели спроса)
  const items = catalog.map((p) => {
    const eff = Number(p.price) * priceMultiplier;
    const pref = affinityOf(persona, p.name) + (p.is_featured ? persona.featuredBonus : 0);
    const affordable = eff <= persona.budget && (p.stock === undefined || p.stock > 0);
    return { p, eff, pref, affordable };
  }).filter((x) => x.affordable);
  if (!items.length) return { bought: false, reason: 'нет доступного по цене/наличию' };

  // выбирает товар по предпочтению (с небольшим шумом)
  items.sort((a, b) => b.pref - a.pref);
  const pick = items[weighted(rng, items.map((x) => Math.max(0.01, x.pref)))];

  // реакция спроса на цену: чем ближе цена к бюджету, тем ниже склонность
  const affordability = clamp01(1 - persona.priceSensitivity * (pick.eff / persona.budget));
  const buyProb = clamp01(persona.conversionBase * clamp01(pick.pref) * (0.4 + 0.6 * affordability));
  if (rng() >= buyProb) return { bought: false, reason: 'не сконвертировался' };

  const qty = 1 + Math.floor(rng() * persona.maxQty * affordability);
  return {
    bought: true,
    product_id: pick.p.id,
    product_name: pick.p.name,
    quantity: qty,
    unit_price: round2(pick.eff),
    line_total: round2(pick.eff * qty),
  };
}

// прогон симуляции. opts: { ticks, arrivalRate, priceMultiplier, seed, personas, onlyPersona }
function simulate(catalog, opts = {}) {
  const personas = opts.personas || require('./personas');
  const pool = opts.onlyPersona ? personas.filter((p) => p.id === opts.onlyPersona) : personas;
  const ticks = Math.max(1, opts.ticks || 24);
  const arrivalRate = Math.max(0, opts.arrivalRate ?? 5);
  const priceMultiplier = opts.priceMultiplier ?? 1;
  const rng = makeRng(opts.seed ?? 42);
  const weights = pool.map((p) => p.weight || 1);

  // локальный склад для эффекта дефицита (не мутирует бэкенд)
  const stock = {}; for (const p of catalog) if (p.stock !== undefined) stock[p.id] = Number(p.stock);

  const series = [];
  const units = {};
  const bySegment = {};
  const orders = [];
  let arrivals = 0, purchases = 0, revenue = 0, abandons = 0;

  for (let t = 0; t < ticks; t++) {
    // приход с суточной волной (синус) + дробный остаток через rng
    const wave = 0.6 + 0.4 * Math.sin((t / ticks) * 2 * Math.PI - Math.PI / 2);
    const expected = arrivalRate * wave;
    const n = Math.floor(expected) + (rng() < (expected - Math.floor(expected)) ? 1 : 0);
    let tPurch = 0, tRev = 0;
    for (let i = 0; i < n; i++) {
      arrivals++;
      const persona = pool[weighted(rng, weights)];
      const view = catalog.map((p) => ({ ...p, stock: stock[p.id] }));
      const d = decide(persona, view, priceMultiplier, rng);
      bySegment[persona.id] = bySegment[persona.id] || { name: persona.name, arrivals: 0, purchases: 0, revenue: 0 };
      bySegment[persona.id].arrivals++;
      if (!d.bought) { abandons++; continue; }
      // ограничение наличием
      const have = stock[d.product_id];
      const qty = have !== undefined ? Math.min(d.quantity, have) : d.quantity;
      if (qty <= 0) { abandons++; continue; }
      if (have !== undefined) stock[d.product_id] -= qty;
      const line = round2(d.unit_price * qty);
      purchases++; tPurch++; revenue += line; tRev += line;
      units[d.product_id] = (units[d.product_id] || 0) + qty;
      bySegment[persona.id].purchases++; bySegment[persona.id].revenue = round2(bySegment[persona.id].revenue + line);
      orders.push({ tick: t, persona: persona.id, product_id: d.product_id, product_name: d.product_name, quantity: qty, unit_price: d.unit_price, line_total: line });
    }
    series.push({ tick: t, arrivals: n, purchases: tPurch, revenue: round2(tRev) });
  }

  const unitsByProduct = catalog.map((p) => ({ id: p.id, name: p.name, units: units[p.id] || 0 }));
  return {
    params: { ticks, arrivalRate, priceMultiplier, seed: opts.seed ?? 42, personas: pool.map((p) => p.id) },
    totals: {
      arrivals, purchases, abandons,
      conversion_rate: arrivals ? round2(purchases / arrivals) : 0,
      revenue: round2(revenue),
      aov: purchases ? round2(revenue / purchases) : 0,
    },
    unitsByProduct,
    bySegment,
    series,
    orders,
  };
}

module.exports = { simulate, decide, affinityOf };
