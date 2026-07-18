// actions.js — из аналитического отчёта строит предлагаемые действия с оценкой
// impact (0..100). Impact определяет судьбу действия: авто-исполнение или эскалация.
const policy = require('./policy');
const clamp = (n) => Math.max(0, Math.min(100, n));
const round2 = (n) => Math.round(n * 100) / 100;

function propose(report, cycleNo) {
  const out = [];
  for (const p of report.products || []) {
    // ДОЗАКАЗ — impact по стоимости закупки относительно бюджета
    if (policy.enabled.reorder && p.needsReorder && p.reorderQty > 0) {
      const cost = round2(p.reorderQty * p.price);
      out.push({
        id: `c${cycleNo}-p${p.id}-reorder`, type: 'reorder', productId: p.id, name: p.name,
        params: { quantity: p.reorderQty, unit_price: p.price, cost },
        impact: clamp((cost / policy.reorderBudget) * 100),
        rationale: `остаток ${p.stock} ≤ точки заказа ${p.reorderPoint} при спросе ${p.dailyRate}/сут`,
      });
    }
    // ЦЕНА — клиентское действие, по умолчанию чувствительное (эскалация)
    if (policy.enabled.price_change && p.price_suggestion.action !== 'hold') {
      const from = p.price_suggestion.from, to = p.price_suggestion.to;
      const deltaPct = from ? Math.abs((to - from) / from) * 100 : 0;
      out.push({
        id: `c${cycleNo}-p${p.id}-price`, type: 'price_change', productId: p.id, name: p.name,
        params: { from, to, deltaPct: round2(deltaPct), direction: p.price_suggestion.action },
        impact: clamp(40 + deltaPct * 2),
        rationale: `${p.price_suggestion.action === 'raise' ? 'поднять' : 'снизить'} цену ${from}→${to} €`,
      });
    }
    // ФЛАГ АНОМАЛИИ — информационное, низкий impact
    if (policy.enabled.flag && p.anomalies.length) {
      out.push({
        id: `c${cycleNo}-p${p.id}-flag`, type: 'flag', productId: p.id, name: p.name,
        params: { anomalies: p.anomalies },
        impact: 5,
        rationale: `аномалия: ${p.anomalies.map((a) => a.type).join(', ')}`,
      });
    }
  }
  return out;
}

module.exports = { propose };
