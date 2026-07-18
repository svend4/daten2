// grid.js — прогноз энергосети: регионы × слоты времени с углеродоёмкостью
// (гCO2/кВт·ч) и ценой (€/кВт·ч). Пространственный арбитраж (eu-north чистый,
// us-east дешёвый но грязный) + временной (суточная синусоида) создают окна,
// в которые выгодно сдвигать отложимую нагрузку. Детерминировано (sin, без времени).
const REGIONS = [
  { id: 'eu-north', baseC: 80, ampC: 20, phaseC: 0.0, baseP: 0.10, ampP: 0.03, phaseP: 0.5 },   // чистый (гидро)
  { id: 'eu-west', baseC: 250, ampC: 80, phaseC: 1.2, baseP: 0.14, ampP: 0.05, phaseP: 1.0 },   // средний
  { id: 'us-east', baseC: 400, ampC: 120, phaseC: 2.4, baseP: 0.08, ampP: 0.06, phaseP: 3.5 },  // грязный, но дешёвый
];

function generate(T = 12) {
  const regions = REGIONS.map((r) => ({
    id: r.id,
    slots: Array.from({ length: T }, (_, s) => {
      const w = (s / T) * 2 * Math.PI;
      return {
        slot: s,
        carbon: Math.max(10, Math.round(r.baseC + r.ampC * Math.sin(w + r.phaseC))),
        price: Math.max(0.02, Math.round((r.baseP + r.ampP * Math.sin(w + r.phaseP)) * 10000) / 10000),
      };
    }),
  }));
  return { T, regions };
}

// min-max нормировка по всей сетке — для смешанной метрики carbon/price
function bounds(grid) {
  let cMin = Infinity, cMax = -Infinity, pMin = Infinity, pMax = -Infinity;
  for (const r of grid.regions) for (const s of r.slots) {
    cMin = Math.min(cMin, s.carbon); cMax = Math.max(cMax, s.carbon);
    pMin = Math.min(pMin, s.price); pMax = Math.max(pMax, s.price);
  }
  return { cMin, cMax, pMin, pMax };
}

function cell(grid, regionId, slot) {
  const r = grid.regions.find((x) => x.id === regionId);
  return r ? r.slots[slot] : null;
}

module.exports = { generate, bounds, cell, REGIONS: REGIONS.map((r) => r.id) };
