// scheduler.js — УГЛЕРОДНО-ОСОЗНАННОЕ планирование. Каждую отложимую работу
// (энергия кВт·ч, дедлайн-слот, допустимые регионы) сдвигаем в самое выгодное
// окно (регион, слот ≤ дедлайна) по смешанной метрике carbon/price — если там
// осталась ёмкость. «Сейчас, дома» (наивный слот 0) всегда доступно как fallback.
// Жадность least-flexible-first: сначала размещаем работы с жёстким дедлайном,
// гибкие добирают оставшуюся зелёную ёмкость. Детерминировано.
const grid = require('./grid');

// смешанная метрика за кВт·ч: w=1 — чистый углерод, w=0 — чистая цена
function metricFn(g, weightCarbon) {
  const b = grid.bounds(g);
  const norm = (v, lo, hi) => (hi > lo ? (v - lo) / (hi - lo) : 0);
  return (cellObj) => weightCarbon * norm(cellObj.carbon, b.cMin, b.cMax) + (1 - weightCarbon) * norm(cellObj.price, b.pMin, b.pMax);
}

function homeOf(job) { return (job.regions && job.regions[0]) || 'eu-west'; }

function schedule(jobs, g, { weightCarbon = 1, capacityPerCell = Infinity } = {}) {
  const metric = metricFn(g, weightCarbon);
  const cap = new Map(); // `${region}:${slot}` → оставшаяся ёмкость
  const capKey = (r, s) => r + ':' + s;
  const remaining = (r, s) => (cap.has(capKey(r, s)) ? cap.get(capKey(r, s)) : capacityPerCell);
  const take = (r, s, e) => cap.set(capKey(r, s), remaining(r, s) - e);

  // порядок: жёсткий дедлайн раньше, крупные раньше, стабильно по id
  const order = jobs.slice().sort((a, b) => (a.deadline - b.deadline) || (b.energy - a.energy) || String(a.id).localeCompare(String(b.id)));

  const assignments = [];
  for (const job of order) {
    const home = homeOf(job);
    const deferrable = job.deferrable !== false;
    const eligibleRegions = job.regions && job.regions.length ? job.regions : [home];
    const maxSlot = deferrable ? Math.min(job.deadline == null ? g.T - 1 : job.deadline, g.T - 1) : 0;

    // наивный вариант всегда доступен: сейчас, дома (без учёта ёмкости)
    let best = { region: home, slot: 0, cellObj: grid.cell(g, home, 0), shifted: false };
    let bestScore = metric(best.cellObj);

    if (deferrable) {
      for (const region of eligibleRegions) {
        for (let s = 0; s <= maxSlot; s++) {
          if (region === home && s === 0) continue;           // это и есть наивный вариант
          if (remaining(region, s) < job.energy - 1e-9) continue; // нет зелёной ёмкости
          const c = grid.cell(g, region, s);
          const score = metric(c);
          if (score < bestScore - 1e-12) { bestScore = score; best = { region, slot: s, cellObj: c, shifted: true }; }
        }
      }
    }
    if (best.shifted) take(best.region, best.slot, job.energy);
    const naive = grid.cell(g, home, 0);
    assignments.push({
      id: job.id, energy: job.energy, deadline: job.deadline, region: best.region, slot: best.slot, shifted: best.shifted,
      carbon: Math.round(job.energy * best.cellObj.carbon * 100) / 100,
      cost: Math.round(job.energy * best.cellObj.price * 10000) / 10000,
      naiveCarbon: Math.round(job.energy * naive.carbon * 100) / 100,
      naiveCost: Math.round(job.energy * naive.price * 10000) / 10000,
    });
  }
  return assignments;
}

module.exports = { schedule, metricFn, homeOf };
