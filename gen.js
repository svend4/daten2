// gen.js — детерминированный ГПСЧ и генераторы случайных валидных входов.
// Один seed → воспроизводимый прогон и повторяемые контрпримеры.
function makeRng(seed) {
  let a = (seed >>> 0) || 1;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const int = (rng, lo, hi) => lo + Math.floor(rng() * (hi - lo + 1));
const pick = (rng, arr) => arr[Math.floor(rng() * arr.length)];

// случайный заказ: 1..maxItems разных товаров, кол-во 1..maxQty
function randomOrder(catalog, rng, maxItems = 3, maxQty = 5) {
  const n = Math.min(int(rng, 1, maxItems), catalog.length);
  const pool = [...catalog];
  const items = [];
  for (let i = 0; i < n; i++) {
    const idx = Math.floor(rng() * pool.length);
    const p = pool.splice(idx, 1)[0];
    items.push({ product_id: p.id, quantity: int(rng, 1, maxQty) });
  }
  return { items };
}

// случайный «токен», которого точно не выдавали
function randomToken(rng) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  const len = int(rng, 6, 20);
  let s = 'FAKE-';
  for (let i = 0; i < len; i++) s += chars[Math.floor(rng() * chars.length)];
  return s;
}

module.exports = { makeRng, int, pick, randomOrder, randomToken };
