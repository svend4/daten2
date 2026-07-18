// cases.js — набор эвал-кейсов. Контрактные (соответствие + инварианты) и
// поведенческие (сценарные диалоги против витрины). Каждый кейс: run(ctx) → результат.
const C = require('./checks');

// ---------- контрактные кейсы (против бэкенда контракта) ----------
const contract = [
  {
    id: 'products-shape', name: 'GET /api/products — форма и типы', weight: 2,
    async run({ http }) {
      const r = await http.get('/api/products');
      const arr = r.body;
      const res = C.all([
        C.status(r, 200, 'статус 200'),
        C.isArray(arr, 'массив'),
        Array.isArray(arr) && arr.length ? C.ok('непустой') : C.bad('пустой каталог'),
        ...(Array.isArray(arr) ? arr.slice(0, 5).flatMap((p) => [C.isNum(p.id, 'id'), C.isStr(p.name, 'name'), C.isNum(Number(p.price), 'price')]) : []),
      ]);
      return { pass: res.ok, detail: res.msg };
    },
  },
  {
    id: 'order-create', name: 'POST /api/orders — создание заказа', weight: 2,
    async run({ http, state }) {
      const prods = (await http.get('/api/products')).body || [];
      const p = prods[0];
      if (!p) return { pass: false, detail: 'нет товаров для заказа' };
      const r = await http.post('/api/orders', { name: 'eval-bot', items: [{ product_id: p.id, quantity: 2 }] });
      state.order = r.body; state.product = p;
      const res = C.all([C.statusIn(r, [200, 201], 'статус 2xx'), C.isStr(r.body && r.body.order_number, 'order_number'), C.isNum(Number(r.body && r.body.total), 'total')]);
      return { pass: res.ok, detail: res.msg };
    },
  },
  {
    id: 'order-total-invariant', name: 'Инвариант: total = Σ цена×кол-во', weight: 2,
    async run({ state }) {
      if (!state.order || !state.product) return { pass: false, detail: 'нет заказа (зависит от order-create)' };
      const expected = Number(state.product.price) * 2;
      const res = C.approx(Number(state.order.total), expected, Math.max(0.01, expected * 0.001), 'total');
      return { pass: res.ok, detail: res.msg };
    },
  },
  {
    id: 'order-lookup', name: 'GET /api/orders/{token} — поиск по токену', weight: 1,
    async run({ http, state }) {
      if (!state.order) return { pass: false, detail: 'нет заказа' };
      const r = await http.get('/api/orders/' + encodeURIComponent(state.order.order_number));
      const res = C.all([C.status(r, 200, 'статус 200'), C.eq(r.body && r.body.order_number, state.order.order_number, 'тот же номер')]);
      return { pass: res.ok, detail: res.msg };
    },
  },
  {
    id: 'order-privacy', name: 'Приватность: чужой токен → 404 (не IDOR)', weight: 2,
    async run({ http, state }) {
      const bogus = (state.order ? state.order.order_number : 'X') + '-NOPE-404';
      const r = await http.get('/api/orders/' + encodeURIComponent(bogus));
      // допустимо: 404/400; НЕдопустимо: 200 с чужим заказом
      const res = r.status === 200 && r.body && r.body.order_number ? C.bad('утечка: вернулся заказ по неверному токену') : C.ok('несуществующий токен закрыт');
      return { pass: res.ok, detail: res.msg };
    },
  },
  {
    id: 'order-validation', name: 'Валидация: пустой заказ → 4xx', weight: 1,
    async run({ http }) {
      const r = await http.post('/api/orders', { name: 'x', items: [] });
      const res = r.status >= 400 && r.status < 500 ? C.ok('отклонён') : C.bad(`ожидался 4xx, получено ${r.status}`);
      return { pass: res.ok, detail: res.msg };
    },
  },
];

// ---------- поведенческие кейсы (против витрины /api/chat) ----------
const PRODUCT_RE = /роз|тюльпан|пион|букет/i;
const behavior = [
  {
    id: 'shows-catalog', name: 'Показывает каталог по запросу', weight: 1,
    async run({ chat }) {
      const d = await chat('покажи каталог');
      const reply = (d && d.reply) || '';
      return { pass: PRODUCT_RE.test(reply) && reply.length > 10, detail: reply.slice(0, 80) };
    },
  },
  {
    id: 'adds-to-cart', name: 'Добавляет товар в корзину', weight: 1,
    async run({ chat }) {
      const d = await chat('добавьте 2 розы');
      const reply = (d && d.reply) || '';
      return { pass: /добав|корзин/i.test(reply), detail: reply.slice(0, 80) };
    },
  },
  {
    id: 'completes-order', name: 'Доводит до оформления заказа', weight: 2,
    async run({ chat }) {
      await chat('оформить заказ');
      const d = await chat('Стефан');
      const reply = (d && d.reply) || '';
      return { pass: /оформлен|заказ|ORD-|номер/i.test(reply), detail: reply.slice(0, 80) };
    },
  },
];

module.exports = { contract, behavior };
