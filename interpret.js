// interpret.js — детерминированная сводка по углеродному арбитражу.
const store = require('./store');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const last = store.getLast();
  if (!last) return { reply: 'План ещё не строился — отправьте нагрузки на планирование.', engine: 'rules' };

  if (/сдвиг|shift|окно|регион|когда|куда/.test(low)) {
    const moved = last.assignments.filter((a) => a.shifted);
    if (!moved.length) return { reply: 'Ни одну нагрузку не удалось сдвинуть выгоднее (дедлайны/ёмкость/уже оптимально).', engine: 'rules' };
    const lines = moved.slice(0, 8).map((a) => `• ${a.id}: → ${a.region}, слот ${a.slot} (было сейчас/дома); CO2 ${a.naiveCarbon}→${a.carbon} г`);
    return { reply: `Сдвинуто ${moved.length} из ${last.jobs} нагрузок:\n` + lines.join('\n'), engine: 'rules' };
  }
  const s = last.savings;
  return { reply: `Углеродный арбитраж: экономия CO2 ${s.carbon} г (${s.carbonPct}%), денег ${s.cost} € (${s.costPct}%). Сдвинуто ${last.shifted}/${last.jobs} нагрузок против наивного «всё сейчас, дома».`, engine: 'rules' };
}
module.exports = { ask };
