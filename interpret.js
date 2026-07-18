// interpret.js — детерминированные ответы о переговорах (фолбэк без ключа).
const store = require('./store');
const money = (n) => Number(n).toFixed(2) + ' €';

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const s = store.stats();
  if (!s.total) return { reply: 'Переговоров ещё не было — запустите сделку.', engine: 'rules' };

  if (/скидк|дисконт|уступ/.test(low)) {
    return { reply: `Средняя скидка по сделкам: ${s.avg_discount_pct}%. Сделок ${s.deals} из ${s.total}.`, engine: 'rules' };
  }
  if (/послед|истори|сделк|результат/.test(low)) {
    const r = store.recent(6);
    return { reply: 'Последние переговоры:\n' + r.map((e) => `• ${e.product} ×${e.quantity}: ${e.deal ? `сделка ${money(e.deal.agreed_unit)}/ед (−${e.deal.discount_pct}%, ${e.deal.rounds} раунд.)` : 'без сделки'}`).join('\n'), engine: 'rules' };
  }
  return { reply: `Всего переговоров ${s.total}: сделок ${s.deals}, без сделки ${s.no_deals}, средняя скидка ${s.avg_discount_pct}%.`, engine: 'rules' };
}
module.exports = { ask };
