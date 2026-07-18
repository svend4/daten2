// model.js — многокритериальный «мозг» green/FinOps-роутера.
// По каждому уровню держит онлайн-оценки латентности и надёжности, а стоимость,
// мощность и углеродоёмкость сети — из профиля. Композитная стоимость взвешивает
// латентность / деньги / углерод / надёжность; выбор = argmin. Плюс учёт FinOps.

const round = (n, d = 4) => { const f = 10 ** d; return Math.round(n * f) / f; };

const CFG = {
  alpha: Number(process.env.EWMA_ALPHA || 0.3),
  latencyPriorMs: Number(process.env.LAT_PRIOR_MS || 50),
  baseJoules: Number(process.env.BASE_JOULES || 0.5), // фикс. энергия на запрос
};

let backends = [];
let weights = {
  latency: Number(process.env.W_LATENCY || 0.4),
  cost: Number(process.env.W_COST || 0.3),
  carbon: Number(process.env.W_CARBON || 0.2),
  reliability: Number(process.env.W_RELIABILITY || 0.1),
};
const state = new Map(); // id -> { latencyEwma, successEwma, alive, n, finops }

function configure(list) {
  backends = list.map((b) => ({ cost: 0.001, watts: 20, grid: 200, ...b }));
  for (const b of backends) if (!state.has(b.id)) state.set(b.id, { latencyEwma: null, successEwma: 1, alive: false, n: 0, finops: { req: 0, costEur: 0, energyJ: 0, co2mg: 0 } });
}
const get = (id) => state.get(id);
const find = (id) => backends.find((b) => b.id === id);

// энергия (Дж) и углерод (мг CO2) одного запроса на уровне
function energyJ(b, latencyMs) { return CFG.baseJoules + b.watts * (latencyMs / 1000); }
function co2mg(b, latencyMs) { const kWh = energyJ(b, latencyMs) / 3.6e6; return kWh * b.grid * 1000; } // g/kWh × kWh = g; ×1000 = мг

// метрики уровня «чем меньше — тем лучше»
function metrics(b) {
  const s = get(b.id);
  const lat = s.latencyEwma == null ? CFG.latencyPriorMs : s.latencyEwma;
  return { latency: lat, cost: b.cost, carbon: co2mg(b, lat), unreliability: 1 - s.successEwma };
}

const norm = (v, min, max) => (max > min ? (v - min) / (max - min) : 0);

function decide() {
  const alive = backends.filter((b) => get(b.id).alive);
  const pool = alive.length ? alive : backends;
  const m = pool.map((b) => ({ b, ...metrics(b) }));
  const ranges = {};
  for (const k of ['latency', 'cost', 'carbon', 'unreliability']) {
    const vals = m.map((x) => x[k]); ranges[k] = [Math.min(...vals), Math.max(...vals)];
  }
  const wsum = weights.latency + weights.cost + weights.carbon + weights.reliability || 1;
  const scored = m.map((x) => {
    const composite = (
      weights.latency * norm(x.latency, ...ranges.latency) +
      weights.cost * norm(x.cost, ...ranges.cost) +
      weights.carbon * norm(x.carbon, ...ranges.carbon) +
      weights.reliability * norm(x.unreliability, ...ranges.unreliability)
    ) / wsum;
    return { id: x.b.id, name: x.b.name, alive: get(x.b.id).alive, composite: round(composite), latencyMs: round(x.latency, 1), costEur: x.b.cost, co2mg: round(x.carbon, 3), success: round(get(x.b.id).successEwma, 3) };
  });
  scored.sort((a, b) => a.composite - b.composite); // меньше композит — лучше
  return { choice: scored[0] ? scored[0].id : null, weights: { ...weights }, scored };
}

function setWeights(w) {
  for (const k of ['latency', 'cost', 'carbon', 'reliability']) if (w[k] != null) weights[k] = Math.max(0, Number(w[k]));
  return { ...weights };
}
const getWeights = () => ({ ...weights });

// учёт факта обслуживания (обновление модели + FinOps)
function recordServed(id, latencyMs, ok) {
  const b = find(id), s = get(id);
  if (!b || !s) return;
  s.n++;
  if (ok && latencyMs != null) s.latencyEwma = s.latencyEwma == null ? latencyMs : s.latencyEwma + CFG.alpha * (latencyMs - s.latencyEwma);
  s.successEwma = s.successEwma + CFG.alpha * ((ok ? 1 : 0) - s.successEwma);
  const f = s.finops; f.req++; f.costEur = round(f.costEur + b.cost, 6); f.energyJ = round(f.energyJ + energyJ(b, latencyMs || 0), 3); f.co2mg = round(f.co2mg + co2mg(b, latencyMs || 0), 3);
}

async function refresh(fetchImpl = fetch) {
  await Promise.all(backends.map(async (b) => {
    const s = get(b.id); const t = Date.now();
    try { const r = await fetchImpl(b.url + '/api/health', { signal: AbortSignal.timeout(2000) }); s.alive = r.ok; const dt = Date.now() - t; if (r.ok) s.latencyEwma = s.latencyEwma == null ? dt : s.latencyEwma + CFG.alpha * (dt - s.latencyEwma); }
    catch { s.alive = false; }
  }));
  return backends.map((b) => ({ id: b.id, alive: get(b.id).alive }));
}

function finops() {
  const per = backends.map((b) => ({ id: b.id, name: b.name, ...get(b.id).finops }));
  const tot = per.reduce((a, p) => ({ req: a.req + p.req, costEur: a.costEur + p.costEur, energyJ: a.energyJ + p.energyJ, co2mg: a.co2mg + p.co2mg }), { req: 0, costEur: 0, energyJ: 0, co2mg: 0 });
  return { perLevel: per, total: { req: tot.req, costEur: round(tot.costEur, 6), energyWh: round(tot.energyJ / 3600, 4), co2g: round(tot.co2mg / 1000, 4) } };
}

module.exports = { configure, decide, setWeights, getWeights, recordServed, refresh, finops, metrics, find, get, energyJ, co2mg };
