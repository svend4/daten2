// interpret.js — детерминированная сводка по событийному потоку (фолбэк без ключа).
function ask(_session, text, state) {
  const low = (text || '').toLowerCase();
  if (!state || !state.eventCount) return { reply: 'Событий пока нет. Опубликуйте события или сделайте снимок каталога.', engine: 'rules' };

  if (/цен|price|подорож|подешев/.test(low)) {
    const ph = state.priceHistory.slice(-6).reverse();
    if (!ph.length) return { reply: 'Изменений цен не зафиксировано.', engine: 'rules' };
    return { reply: 'Изменения цен:\n' + ph.map((p) => `• ${p.name || p.product_id}: ${p.from} → ${p.to}`).join('\n'), engine: 'rules' };
  }
  if (/заказ|выручк|order|revenue|продаж/.test(low)) {
    return { reply: `Заказов: ${state.orders.count}, выручка ${state.orders.revenue} €.`, engine: 'rules' };
  }
  if (/тип|type|событ|поток/.test(low)) {
    const t = Object.entries(state.byType).sort((a, b) => b[1] - a[1]);
    return { reply: 'События по типам:\n' + t.map(([k, v]) => `• ${k}: ${v}`).join('\n'), engine: 'rules' };
  }
  return { reply: `Всего событий ${state.eventCount} (до seq ${state.lastSeq}). Заказов ${state.orders.count}, выручка ${state.orders.revenue} €. Типов: ${Object.keys(state.byType).length}.`, engine: 'rules' };
}
module.exports = { ask };
