// brain.js — «мозг» роутера: онлайн-модель и выбор бэкенда.
// Для каждого уровня держит скользящие оценки латентности и надёжности, учитывает
// текущую нагрузку и стоимость. Выбор — UCB1 поверх этой полезности: эксплуатируем
// лучший уровень, но иногда пробуем недоисследованные (само­оптимизация). После
// каждого ответа модель обновляется реально измеренными латентностью и исходом.

const CFG = {
  latencyCap: Number(process.env.LATENCY_CAP_MS || 500), // мс, шкала «медленно»
  explore: Number(process.env.EXPLORE_C || 0.3),          // коэффициент разведки UCB
  loadPenalty: Number(process.env.LOAD_PENALTY || 0.5),   // штраф за конкурентные запросы
  alpha: Number(process.env.EWMA_ALPHA || 0.3),           // скорость обучения EWMA
};

const round = (n) => Math.round(n * 1000) / 1000;

let backends = [];
const state = new Map(); // id -> { latencyEwma, successEwma, inflight, n, alive }

function configure(list) {
  backends = list.map((b) => ({ cost: 1, ...b }));
  for (const b of backends) {
    if (!state.has(b.id)) state.set(b.id, { latencyEwma: null, successEwma: 1, inflight: 0, n: 0, alive: false });
  }
}
const get = (id) => state.get(id);
const find = (id) => backends.find((b) => b.id === id);

// Полезность бэкенда: выше — лучше. Быстрый, надёжный, дешёвый и незагруженный.
function utility(b) {
  const s = get(b.id);
  const lat = s.latencyEwma == null ? CFG.latencyCap * 0.3 : s.latencyEwma; // оптимистичный приор
  const latencyScore = CFG.latencyCap / (CFG.latencyCap + lat);             // (0..1], быстрее → выше
  const load = 1 + s.inflight * CFG.loadPenalty;                            // нагрузка снижает полезность
  return (s.successEwma * latencyScore) / b.cost / load;
}

// Решение: UCB1 = полезность + бонус разведки (падает с числом проб).
function decide() {
  const alive = backends.filter((b) => get(b.id).alive);
  const pool = alive.length ? alive : backends; // никого живого — пробуем всех
  const total = pool.reduce((t, b) => t + get(b.id).n, 0);
  const scored = pool.map((b) => {
    const s = get(b.id);
    const u = utility(b);
    const bonus = CFG.explore * Math.sqrt(Math.log(total + 1) / (s.n + 1));
    return {
      id: b.id, name: b.name, cost: b.cost, alive: s.alive, n: s.n,
      inflight: s.inflight, success: round(s.successEwma),
      latencyEwma: s.latencyEwma == null ? null : round(s.latencyEwma),
      utility: round(u), bonus: round(bonus), score: round(u + bonus),
    };
  });
  scored.sort((a, b) => b.score - a.score);
  return { choice: scored[0] ? scored[0].id : null, scored };
}

function start(id) { const s = get(id); if (s) s.inflight++; }

// Обучение на исходе: EWMA латентности (по успехам) и надёжности (по всем).
function record(id, { latencyMs, ok }) {
  const s = get(id);
  if (!s) return;
  s.inflight = Math.max(0, s.inflight - 1);
  s.n++;
  if (ok && latencyMs != null) {
    s.latencyEwma = s.latencyEwma == null ? latencyMs : s.latencyEwma + CFG.alpha * (latencyMs - s.latencyEwma);
  }
  s.successEwma = s.successEwma + CFG.alpha * ((ok ? 1 : 0) - s.successEwma);
}

// Опрос здоровья бэкендов (кто в пуле).
async function refresh(fetchImpl = fetch) {
  await Promise.all(backends.map(async (b) => {
    try {
      const r = await fetchImpl(b.url + '/api/health', { signal: AbortSignal.timeout(1500) });
      get(b.id).alive = r.ok;
    } catch { get(b.id).alive = false; }
  }));
  return backends.map((b) => ({ id: b.id, alive: get(b.id).alive }));
}

function snapshot() {
  return backends.map((b) => {
    const s = get(b.id);
    return {
      id: b.id, name: b.name, cost: b.cost, alive: s.alive, n: s.n, inflight: s.inflight,
      success: round(s.successEwma), latencyEwma: s.latencyEwma == null ? null : round(s.latencyEwma),
      utility: round(utility(b)),
    };
  });
}

module.exports = { CFG, configure, decide, start, record, refresh, snapshot, find, get };
