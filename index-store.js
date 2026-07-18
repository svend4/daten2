// index-store.js — векторный индекс каталога в памяти.
// Тянет товары через контракт, кодирует их в семантические векторы и обслуживает
// поиск (cosine к вектору запроса) и рекомендации (cosine между товарами).
const contract = require('./contract');
const enc = require('./encoder');

let items = []; // [{ product, vec }]

function priceAffordabilities(products) {
  const prices = products.map((p) => Number(p.price)).filter((x) => !Number.isNaN(x));
  const min = Math.min(...prices), max = Math.max(...prices);
  const span = max - min;
  return (price) => (span > 0 ? 1 - (Number(price) - min) / span : 0.5); // дешевле → доступнее
}

async function build() {
  const products = await contract.listProducts();
  const afford = priceAffordabilities(products);
  items = products.map((p) => ({ product: p, vec: enc.encodeProduct(p, afford(p.price)) }));
  return items.length;
}

const size = () => items.length;
const byId = (id) => items.find((it) => String(it.product.id) === String(id));

function present(it, score, qv) {
  const p = it.product;
  return {
    id: p.id, name: p.name, price: Number(p.price), currency: p.currency || 'EUR',
    is_featured: !!p.is_featured, stock: p.stock,
    score: Math.round(score * 1000) / 1000,
    matched: qv ? enc.matchedAxes(qv, it.vec) : [],
  };
}

// Поиск. encodeQuery — функция text→вектор (детерминированная или LLM).
async function search(query, top = 5, encodeQuery) {
  const qv = encodeQuery ? await encodeQuery(query) : enc.encodeText(query);
  let ranked;
  if (enc.norm(qv) === 0) {
    // запрос без смысловых осей — фолбэк на совпадение по названию
    const q = String(query || '').toLowerCase();
    ranked = items
      .map((it) => ({ it, score: it.product.name.toLowerCase().includes(q) && q ? 1 : 0 }))
      .filter((r) => r.score > 0);
    if (!ranked.length) ranked = items.map((it) => ({ it, score: it.product.is_featured ? 0.5 : 0.1 }));
  } else {
    ranked = items.map((it) => ({ it, score: enc.cosine(qv, it.vec) })).filter((r) => r.score > 0.01);
  }
  ranked.sort((a, b) => b.score - a.score);
  return { query, axes: qv, results: ranked.slice(0, top).map((r) => present(r.it, r.score, qv)) };
}

// Похожие товары (рекомендации) по векторной близости.
function similar(id, top = 3) {
  const target = byId(id);
  if (!target) return null;
  const ranked = items
    .filter((it) => it !== target)
    .map((it) => ({ it, score: enc.cosine(target.vec, it.vec) }))
    .sort((a, b) => b.score - a.score);
  return { of: present(target, 1), results: ranked.slice(0, top).map((r) => present(r.it, r.score)) };
}

module.exports = { build, size, search, similar, byId };
