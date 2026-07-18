// project.js — СЕМАНТИЧЕСКАЯ ПРОЕКЦИЯ ответа в каноническую форму.
// Здесь закодировано, ЧТО обязано совпадать у всех языковых портов (наблюдаемое
// поведение), а что вправе различаться (внутренние детали). Волатильные поля
// (токен заказа, автоинкремент-id, метки времени, картинки) нормализуются —
// иначе каждый порт «расходился» бы на них, хотя это не расхождение поведения.

const num = (x) => (x == null || x === '' ? null : Math.round(Number(x) * 100) / 100); // до копеек
const byName = (a, b) => String(a.name).localeCompare(String(b.name));
const arr = (x, ...keys) => { for (const k of keys) if (Array.isArray(x && x[k])) return x[k]; return Array.isArray(x) ? x : []; };
const pick = (o, ...keys) => { for (const k of keys) if (o && o[k] != null) return o[k]; return undefined; };

// health: метка уровня У ВСЕХ РАЗНАЯ (это by design) → сверяем только живость.
function health(b) {
  return { ok: !!(b && (b.ok === true || b.status === 'ok' || b.healthy === true || b.status === 'healthy')) };
}

// products: каталог обязан быть эквивалентен по НАБОРУ товаров (имя/цена/активность).
// id и картинки — внутреннее, нормализуются прочь; сортировка по имени убирает
// зависимость от порядка выборки.
function products(list) {
  return arr(list, 'products', 'items', 'data')
    .map((p) => ({ name: pick(p, 'name', 'title'), price: num(pick(p, 'price', 'unit_price')), active: pick(p, 'active') !== false }))
    .sort(byName);
}

// создание заказа: сумма обязана совпадать; сам токен волатилен → сверяем лишь наличие.
function orderCreate(o) {
  return { total: num(pick(o, 'total', 'total_amount', 'sum')), hasOrderNumber: !!pick(o, 'order_number', 'orderNumber', 'number') };
}

// заказ по токену: статус, состав (имя/кол-во/цена) и сумма обязаны совпадать.
function orderGet(o) {
  const items = arr(o, 'items', 'order_items', 'lines')
    .map((i) => ({ name: pick(i, 'name', 'product_name', 'title'), quantity: num(pick(i, 'quantity', 'qty', 'count')), price: num(pick(i, 'price', 'unit_price')) }))
    .sort(byName);
  return { status: pick(o, 'status', 'state'), total: num(pick(o, 'total', 'total_amount', 'sum')), items };
}

module.exports = { health, products, orderCreate, orderGet };
