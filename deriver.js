// deriver.js — деривация доменных событий из снимков каталога (event sourcing поверх
// read-only контракта): сравнивает предыдущий и новый снимок и выдаёт StockChanged /
// PriceChanged / ProductAdded / ProductRemoved. Так события рождаются даже там, где
// уровень не публикует их сам.
function derive(prev, next) {
  const out = [];
  const pm = new Map((prev || []).map((p) => [p.id, p]));
  for (const n of next || []) {
    const p = pm.get(n.id);
    if (!p) { out.push({ type: 'ProductAdded', payload: { product_id: n.id, name: n.name, price: Number(n.price), stock: Number(n.stock) } }); continue; }
    if (Number(p.stock) !== Number(n.stock)) out.push({ type: 'StockChanged', payload: { product_id: n.id, name: n.name, from: Number(p.stock), to: Number(n.stock), delta: Number(n.stock) - Number(p.stock) } });
    if (Number(p.price) !== Number(n.price)) out.push({ type: 'PriceChanged', payload: { product_id: n.id, name: n.name, from: Number(p.price), to: Number(n.price) } });
  }
  const nm = new Set((next || []).map((n) => n.id));
  for (const p of prev || []) if (!nm.has(p.id)) out.push({ type: 'ProductRemoved', payload: { product_id: p.id, name: p.name } });
  return out;
}
module.exports = { derive };
