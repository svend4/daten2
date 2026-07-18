// search.js — COVERAGE-GUIDED ЭВОЛЮЦИОННЫЙ red-team. Ищем не одну заранее заданную
// атаку, а ОПТИМИЗИРУЕМ по пространству атак: геном = веса по тактикам + число
// тактик k + интенсивность. Фенотип = топ-k тактик по весу, применённые в одной
// сессии; фитнес = число РАЗНЫХ найденных нарушений (плюс бонус за «мягкость» —
// сломать цель низкой интенсивностью опаснее). GA (турнир+кроссовер+мутация+элитизм)
// сходится к геному, максимально ломающему цель. Всё детерминировано (mulberry32).
const tactics = require('./tactics');
const { client } = require('./agent');

function mulberry32(seed) {
  let t = seed >>> 0;
  return () => { t += 0x6d2b79f5; let x = Math.imul(t ^ (t >>> 15), 1 | t); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; };
}

const T = tactics.ids.length;
function randomGenome(rnd) {
  return { weights: Array.from({ length: T }, () => rnd()), k: 1 + Math.floor(rnd() * T), intensity: rnd() };
}
function topK(genome) {
  return tactics.ids.map((id, i) => ({ id, w: genome.weights[i] })).sort((a, b) => b.w - a.w).slice(0, genome.k).map((x) => x.id);
}

// оценка генома: применить топ-k проб в одной сессии, посчитать нарушения
async function evaluate(genome, agentBase, path) {
  const agent = client(agentBase, path);
  const chosen = topK(genome);
  const probes = [];
  for (const id of chosen) probes.push(await tactics.probe(tactics.byId[id], agent, genome.intensity));
  const violated = probes.filter((p) => p.violated);
  const distinct = new Set(violated.map((p) => p.id)).size;
  // фитнес: число нарушений + бонус за мягкость (меньше интенсивность — опаснее)
  const fitness = distinct + (distinct > 0 ? (1 - genome.intensity) * 0.1 : 0);
  return { genome, chosen, probes, violated, distinct, fitness };
}

function tournament(pop, rnd, size = 3) {
  let best = null;
  for (let i = 0; i < size; i++) { const c = pop[Math.floor(rnd() * pop.length)]; if (!best || c.fitness > best.fitness) best = c; }
  return best.genome;
}
function crossover(a, b, rnd) {
  return { weights: a.weights.map((w, i) => (rnd() < 0.5 ? w : b.weights[i])), k: rnd() < 0.5 ? a.k : b.k, intensity: rnd() < 0.5 ? a.intensity : b.intensity };
}
function mutate(g, rnd, rate = 0.3) {
  const weights = g.weights.map((w) => (rnd() < rate ? Math.min(1, Math.max(0, w + (rnd() - 0.5) * 0.6)) : w));
  let k = g.k, intensity = g.intensity;
  if (rnd() < rate) k = Math.min(T, Math.max(1, k + (rnd() < 0.5 ? -1 : 1)));
  if (rnd() < rate) intensity = Math.min(1, Math.max(0, intensity + (rnd() - 0.5) * 0.5));
  return { weights, k, intensity };
}

async function hunt(agentBase, { generations = 6, pop = 12, seed = 1, path } = {}) {
  const rnd = mulberry32(seed);
  let population = Array.from({ length: pop }, () => randomGenome(rnd));
  const brokenEver = new Set();
  const trace = [];
  let best = null;
  const attacksById = new Map(); // лучший (мягчайший) воспроизводимый эксплойт на тактику

  for (let gen = 0; gen < generations; gen++) {
    const scored = [];
    for (const g of population) scored.push(await evaluate(g, agentBase, path));
    scored.sort((a, b) => b.fitness - a.fitness);
    for (const s of scored) for (const v of s.violated) {
      brokenEver.add(v.id);
      const prev = attacksById.get(v.id);
      if (!prev || s.genome.intensity < prev.intensity) attacksById.set(v.id, { tactic: v.id, category: v.category, message: v.message, reply: v.reply, evidence: v.evidence, intensity: s.genome.intensity });
    }
    if (!best || scored[0].fitness > best.fitness) best = scored[0];
    trace.push({ gen, bestFitness: Math.round(scored[0].fitness * 1000) / 1000, distinct: scored[0].distinct, brokenSoFar: brokenEver.size });

    // следующее поколение: элитизм + потомки
    const elite = scored.slice(0, Math.max(1, Math.floor(pop * 0.2))).map((s) => s.genome);
    const next = [...elite];
    while (next.length < pop) next.push(mutate(crossover(tournament(scored, rnd), tournament(scored, rnd), rnd), rnd));
    population = next;
  }

  const attackSurface = tactics.ids.filter((id) => brokenEver.has(id));
  return {
    agent: best.probes.length ? agentBase : agentBase,
    generations, pop,
    bestFitness: Math.round(best.fitness * 1000) / 1000,
    distinctBroken: brokenEver.size,
    totalTactics: T,
    robustness: Math.round((1 - brokenEver.size / T) * 1000) / 1000,
    attackSurface,
    exploits: attackSurface.map((id) => attacksById.get(id)),
    trace,
  };
}

module.exports = { hunt, evaluate, topK, mulberry32 };
