// invariants.js — проверки корректности плана (для тестов и рантайма).
const grid = require('./grid');
const { homeOf } = require('./scheduler');

function check(jobsById, g, result, capacityPerCell = Infinity) {
  const problems = [];
  const load = new Map(); // ёмкость по зелёным (сдвинутым) ячейкам
  for (const a of result.assignments) {
    const job = jobsById[a.id];
    // дедлайн
    const maxSlot = job.deferrable === false ? 0 : (job.deadline == null ? g.T - 1 : job.deadline);
    if (a.slot > maxSlot) problems.push(`${a.id}: слот ${a.slot} > дедлайна ${maxSlot}`);
    // допустимость региона
    const eligible = job.regions && job.regions.length ? job.regions : [homeOf(job)];
    if (!eligible.includes(a.region)) problems.push(`${a.id}: регион ${a.region} вне допустимых`);
    // углерод не хуже наивного при углеродной цели
    if ((result.weightCarbon === 1) && a.carbon > a.naiveCarbon + 1e-6) problems.push(`${a.id}: углерод ${a.carbon} > наивного ${a.naiveCarbon}`);
    // ёмкость зелёных ячеек
    if (a.shifted) { const k = a.region + ':' + a.slot; load.set(k, (load.get(k) || 0) + a.energy); }
  }
  for (const [k, e] of load) if (e > capacityPerCell + 1e-9) problems.push(`ёмкость ${k} превышена: ${e} > ${capacityPerCell}`);
  return { ok: problems.length === 0, problems };
}
module.exports = { check };
