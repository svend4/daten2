// qa.js — детерминированные ответы управляющего (фолбэк без LLM-ключа).
// Формулирует выводы из отчёта ядра на естественном языке (RU).
const analytics = require('./analytics');
const store = require('./store');

const money = (n) => Number(n).toFixed(2) + ' €';

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const rep = analytics.report(store.all());
  if (!rep.generatedFrom) return { reply: 'Пока нет данных — соберите хотя бы один снимок каталога (кнопка «Снимок»).', engine: 'rules' };

  // дозаказы
  if (/дозаказ|заказать|закуп|пополн|остат|склад|запас/.test(low)) {
    if (!rep.reorders.length) return { reply: 'Дозаказ не требуется: у всех товаров запас выше точки заказа.', engine: 'rules' };
    const lines = rep.reorders.map((r) => `• ${r.name}: остаток ${r.stock}, точка заказа ${r.reorderPoint}, спрос ${r.dailyRate}/сут → заказать +${r.quantity}`);
    return { reply: 'Рекомендую дозаказать:\n' + lines.join('\n'), engine: 'rules' };
  }
  // аномалии
  if (/аномал|странн|скачок|подозр|всплеск|провал/.test(low)) {
    if (!rep.anomalies.length) return { reply: 'Аномалий не обнаружено.', engine: 'rules' };
    const lines = rep.anomalies.map((a) => `• ${a.product}: ${a.type} — ${a.detail}`);
    return { reply: 'Замечены аномалии:\n' + lines.join('\n'), engine: 'rules' };
  }
  // цены
  if (/цен|стоимост|подорож|скидк|наценк|прайс/.test(low)) {
    const s = rep.price_suggestions;
    if (!s.length) return { reply: 'Цены менять не нужно — спрос и запасы сбалансированы.', engine: 'rules' };
    const lines = s.map((p) => `• ${p.name}: ${p.action === 'raise' ? 'поднять' : 'снизить'} ${money(p.from)} → ${money(p.to)} (${p.reason})`);
    return { reply: 'Подсказки по ценам:\n' + lines.join('\n'), engine: 'rules' };
  }
  // прогноз / исчерпание
  if (/прогноз|спрос|закончит|исчерп|хватит|сколько.*дн/.test(low)) {
    const lines = rep.products.map((p) => `• ${p.name}: спрос ${p.dailyRate}/сут, ${p.daysToStockout === null ? 'не расходуется' : `хватит на ~${p.daysToStockout} дн.`}`);
    return { reply: 'Прогноз по остаткам:\n' + lines.join('\n'), engine: 'rules' };
  }
  // сводка по умолчанию
  return { reply: rep.summary, engine: 'rules' };
}

module.exports = { ask };
