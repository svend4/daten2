// properties.js — инварианты контракта как СВОЙСТВА (проверяются на многих
// сгенерированных входах, а не на примерах). У каждого свойства есть генератор,
// проверка и функция сжатия (shrink) для минимального контрпримера.
const gen = require('./gen');
const enc = encodeURIComponent;
const round2 = (n) => Math.round(n * 100) / 100;

// shrink для заказа: убрать по одной позиции; уменьшить количества вдвое
function shrinkOrder(input) {
  const out = [];
  const items = input.items;
  if (items.length > 1) for (let i = 0; i < items.length; i++) out.push({ items: items.filter((_, j) => j !== i) });
  for (let i = 0; i < items.length; i++) {
    const q = items[i].quantity;
    if (q > 1) { const cp = items.map((it, j) => (j === i ? { ...it, quantity: Math.floor(q / 2) || 1 } : it)); out.push({ items: cp }); }
  }
  return out;
}

module.exports = [
  {
    id: 'total-invariant', name: 'total = Σ (цена × количество)',
    gen: (ctx, rng) => gen.randomOrder(ctx.catalog, rng),
    shrink: shrinkOrder,
    async prop(ctx, input) {
      const expected = round2(input.items.reduce((s, it) => s + ctx.priceOf(it.product_id) * it.quantity, 0));
      const r = await ctx.http.post('/api/orders', { name: 'prop', items: input.items });
      if (![200, 201].includes(r.status)) return { ok: false, detail: `заказ отклонён (${r.status})` };
      const total = Number(r.body && r.body.total);
      return { ok: Math.abs(total - expected) <= 0.01, detail: `ждали total=${expected}, получили ${total}` };
    },
  },
  {
    id: 'order-retrievable', name: 'заказ находится по своему токену',
    gen: (ctx, rng) => gen.randomOrder(ctx.catalog, rng),
    shrink: shrinkOrder,
    async prop(ctx, input) {
      const r = await ctx.http.post('/api/orders', { name: 'prop', items: input.items });
      const token = r.body && r.body.order_number;
      if (!token) return { ok: false, detail: 'нет order_number' };
      const g = await ctx.http.get('/api/orders/' + enc(token));
      return { ok: g.status === 200 && g.body && g.body.order_number === token, detail: `GET по токену → ${g.status}` };
    },
  },
  {
    id: 'token-privacy', name: 'невыданный токен → не отдаёт заказ (нет IDOR)',
    gen: (_ctx, rng) => ({ token: gen.randomToken(rng) }),
    shrink: (input) => (input.token.length > 6 ? [{ token: input.token.slice(0, Math.max(6, Math.floor(input.token.length / 2))) }, { token: 'FAKE-X' }] : []),
    async prop(ctx, input) {
      const g = await ctx.http.get('/api/orders/' + enc(input.token));
      const leaked = g.status === 200 && g.body && g.body.order_number;
      return { ok: !leaked, detail: leaked ? `утечка: вернулся заказ ${g.body.order_number}` : '404 ок' };
    },
  },
  {
    id: 'distinct-tokens', name: 'разные заказы → разные токены',
    gen: (ctx, rng) => ({ a: gen.randomOrder(ctx.catalog, rng), b: gen.randomOrder(ctx.catalog, rng) }),
    shrink: (input) => [{ a: { items: input.a.items.slice(0, 1) }, b: { items: input.b.items.slice(0, 1) } }],
    async prop(ctx, input) {
      const ra = await ctx.http.post('/api/orders', { name: 'a', items: input.a.items });
      const rb = await ctx.http.post('/api/orders', { name: 'b', items: input.b.items });
      const ta = ra.body && ra.body.order_number, tb = rb.body && rb.body.order_number;
      return { ok: !!ta && !!tb && ta !== tb, detail: `токены: ${ta} / ${tb}` };
    },
  },
  {
    id: 'read-idempotent', name: 'GET /api/products идемпотентен',
    gen: () => ({}),
    shrink: () => [],
    async prop(ctx) {
      const a = await ctx.http.get('/api/products');
      const b = await ctx.http.get('/api/products');
      return { ok: JSON.stringify(a.body) === JSON.stringify(b.body), detail: 'два чтения каталога различаются' };
    },
  },
];
