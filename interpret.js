// interpret.js — детерминированные объяснения решений green-роутера (фолбэк без ключа).
const model = require('./model');

const eur = (n) => '€' + Number(n).toFixed(4);

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const { choice, scored, weights } = model.decide();
  if (!scored.length) return { reply: 'Пул уровней пуст.', engine: 'rules' };

  if (/finops|стоимост|деньг|потрач|расход|бюджет/.test(low)) {
    const f = model.finops();
    return { reply: `FinOps: обслужено ${f.total.req} запросов, потрачено ${eur(f.total.costEur)}, энергия ${f.total.energyWh} Вт·ч, выбросы ${f.total.co2g} г CO2.`, engine: 'rules' };
  }
  if (/углерод|co2|эколог|green|зелён|выброс/.test(low)) {
    const byco2 = [...scored].sort((a, b) => a.co2mg - b.co2mg);
    return { reply: 'Углеродный след (мг CO2/запрос):\n' + byco2.map((s) => `• ${s.name}: ${s.co2mg}`).join('\n'), engine: 'rules' };
  }
  if (/вес|критери|баланс|настрой/.test(low)) {
    return { reply: `Веса: латентность ${weights.latency}, стоимость ${weights.cost}, углерод ${weights.carbon}, надёжность ${weights.reliability}.`, engine: 'rules' };
  }
  const top = scored[0];
  return { reply: `Сейчас выбран «${top.name}» (композит ${top.composite}): латентность ${top.latencyMs} мс, ${eur(top.costEur)}/запрос, ${top.co2mg} мг CO2. Веса: лат ${weights.latency} / цена ${weights.cost} / углерод ${weights.carbon}.`, engine: 'rules', choice };
}
module.exports = { ask };
