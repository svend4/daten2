// scorecard.js — хранение прогонов, baseline и обнаружение регрессий.
const store = { last: null, baseline: null };

function record(card) { store.last = card; return card; }
function setBaseline(card) { store.baseline = card; return store.baseline; }
const getLast = () => store.last;
const getBaseline = () => store.baseline;

// регрессии: кейсы, что проходили в baseline, но упали сейчас (и наоборот — исправления)
function compare(current, baseline) {
  if (!baseline) return { hasBaseline: false, regressions: [], fixes: [], scoreDelta: null };
  const bmap = Object.fromEntries((baseline.results || []).map((r) => [r.id, r.pass]));
  const regressions = [], fixes = [];
  for (const r of current.results || []) {
    const was = bmap[r.id];
    if (was === true && !r.pass) regressions.push({ id: r.id, name: r.name, detail: r.detail });
    if (was === false && r.pass) fixes.push({ id: r.id, name: r.name });
  }
  return { hasBaseline: true, regressions, fixes, scoreDelta: Math.round((current.score - baseline.score) * 10) / 10 };
}

module.exports = { record, setBaseline, getLast, getBaseline, compare };
