// interpret.js — детерминированная интерпретация прогонов двойника (фолбэк без ключа).
const store = require('./store');

const money = (n) => Number(n).toFixed(2) + ' €';

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const run = store.get();
  if (!run) return { reply: 'Симуляция ещё не запускалась — нажмите «Прогнать».', engine: 'rules' };
  const t = run.totals;

  // сегменты
  if (/сегмент|персон|покупател|кто.*покупа|аудитор/.test(low)) {
    const seg = Object.values(run.bySegment || {}).sort((a, b) => b.revenue - a.revenue);
    if (!seg.length) return { reply: 'Нет данных по сегментам.', engine: 'rules' };
    return { reply: 'Выручка по сегментам:\n' + seg.map((s) => `• ${s.name}: ${money(s.revenue)} (конверсия ${s.arrivals ? Math.round((s.purchases / s.arrivals) * 100) : 0}%)`).join('\n'), engine: 'rules' };
  }
  // товары / бестселлеры
  if (/товар|бестселлер|продал|популярн|units|штук/.test(low)) {
    const u = [...(run.unitsByProduct || [])].sort((a, b) => b.units - a.units);
    return { reply: 'Продано по товарам:\n' + u.map((x) => `• ${x.name}: ${x.units} шт.`).join('\n'), engine: 'rules' };
  }
  // what-if
  if (run.whatif && /what|цен|наценк|скидк|сценар|подорож|подешев/.test(low)) {
    const w = run.whatif;
    return { reply: `What-if по цене:\n• базовая: выручка ${money(w.baseline.revenue)}, конверсия ${Math.round(w.baseline.conversion_rate * 100)}%\n• ×${w.multiplier}: выручка ${money(w.scenario.revenue)}, конверсия ${Math.round(w.scenario.conversion_rate * 100)}%\nИтог: выручка ${w.delta_revenue >= 0 ? '+' : ''}${money(w.delta_revenue)}, конверсия ${w.delta_conversion >= 0 ? '+' : ''}${Math.round(w.delta_conversion * 100)} п.п.`, engine: 'rules' };
  }
  // сводка
  const parts = [
    `Прогон: ${t.arrivals} посетителей, ${t.purchases} покупок (конверсия ${Math.round(t.conversion_rate * 100)}%).`,
    `Выручка ${money(t.revenue)}, средний чек ${money(t.aov)}.`,
  ];
  if (run.mode === 'live') parts.push(`Оформлено на бэкенде: ${run.placed_orders} заказов${run.failed_orders ? `, ошибок ${run.failed_orders}` : ''}.`);
  return { reply: parts.join(' '), engine: 'rules' };
}

module.exports = { ask };
