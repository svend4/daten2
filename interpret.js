// interpret.js — детерминированная сводка по property-прогону (фолбэк без ключа).
const store = require('./store');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const last = store.get();
  if (!last) return { reply: 'Property-прогон ещё не запускался.', engine: 'rules' };
  if (!last.allHold || /контрпример|провал|counter|наруш/.test(low)) {
    const fails = last.results.filter((r) => !r.ok);
    if (!fails.length) return { reply: `Все ${last.total} свойств держатся на ${last.iterations} входах.`, engine: 'rules' };
    return { reply: `Нарушенные свойства (${fails.length}):\n` + fails.map((f) => `• ${f.name}: ${f.detail}\n  контрпример: ${JSON.stringify(f.counterexample)} (сжат за ${f.shrinkSteps} шагов)`).join('\n'), engine: 'rules' };
  }
  return { reply: `Инварианты держатся: ${last.held}/${last.total} свойств на ${last.iterations} сгенерированных входах против ${last.target}.`, engine: 'rules' };
}
module.exports = { ask };
