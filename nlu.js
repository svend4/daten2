// nlu.js — детерминированный диалоговый движок (фолбэк без LLM-ключа).
// Понимает базовый сценарий покупки на естественном языке (RU).
const shop = require('./shop');

const money = (n) => Number(n).toFixed(2) + ' €';
const cartTotal = (cart) => cart.reduce((s, it) => s + it.price * it.qty, 0);

function findProduct(products, text) {
  const t = text.toLowerCase();
  // по корню названия
  const roots = [['роз', 'роза'], ['тюльпан', 'тюльпан'], ['пион', 'пион']];
  for (const [root] of roots) {
    if (t.includes(root)) {
      const p = products.find((x) => x.name.toLowerCase().includes(root));
      if (p) return p;
    }
  }
  // прямое вхождение полного названия
  return products.find((x) => t.includes(x.name.toLowerCase())) || null;
}

function parseQty(text) {
  const m = text.match(/(\d+)\s*(шт|штук)?/);
  return m ? Math.max(1, parseInt(m[1], 10)) : 1;
}

function catalogReply(products) {
  const lines = products.map(
    (p) => `• ${p.name} — ${money(p.price)}${p.is_featured ? ' ★' : ''} (в наличии: ${p.stock})`
  );
  return 'Вот наш ассортимент:\n' + lines.join('\n') + '\n\nСкажите, например: «добавьте 2 розы» или «оформить заказ».';
}

async function handle(session, text) {
  const msg = (text || '').trim();
  const low = msg.toLowerCase();
  session.cart = session.cart || [];

  // ожидаем имя для оформления
  if (session.awaiting === 'name') {
    session.awaiting = null;
    const name = msg;
    if (!name) return { reply: 'Нужно имя для заказа. Как вас зовут?', cart: session.cart };
    try {
      const res = await shop.createOrder({
        name, phone: '', email: '', address: '',
        items: session.cart.map((it) => ({ product_id: it.product_id, quantity: it.qty })),
      });
      const total = money(res.total);
      session.cart = [];
      return { reply: `Готово, ${name}! Заказ оформлен на сумму ${total}.\nНомер для отслеживания: ${res.order_number}`, cart: [] };
    } catch (e) {
      return { reply: 'Не удалось оформить заказ: ' + e.message, cart: session.cart };
    }
  }

  // приветствие / помощь
  if (/привет|здравств|начн|помощ|что ты уме|что умеешь/.test(low) || !msg) {
    return { reply: 'Здравствуйте! Я помогу выбрать и заказать цветы 🌷 Спросите «покажи каталог», «есть розы до 2 евро?» или сразу «добавьте пион».', cart: session.cart };
  }

  const products = await shop.listProducts();

  // корзина
  if (/корзин/.test(low)) {
    if (!session.cart.length) return { reply: 'Корзина пуста. Скажите, что добавить.', cart: session.cart };
    const lines = session.cart.map((it) => `• ${it.name} × ${it.qty} — ${money(it.price * it.qty)}`);
    return { reply: 'В корзине:\n' + lines.join('\n') + `\nИтого: ${money(cartTotal(session.cart))}\nСкажите «оформить заказ», когда будете готовы.`, cart: session.cart };
  }

  // очистить
  if (/очист|удали всё|сброс/.test(low)) {
    session.cart = [];
    return { reply: 'Корзина очищена.', cart: [] };
  }

  // оформление
  if (/оформ|заказ|куплю всё|купить всё|checkout|оплат/.test(low) && !/добав/.test(low)) {
    if (!session.cart.length) return { reply: 'Корзина пуста — сначала добавьте товары.', cart: session.cart };
    session.awaiting = 'name';
    return { reply: `Оформляю заказ на ${money(cartTotal(session.cart))}. На какое имя?`, cart: session.cart };
  }

  // добавление в корзину
  if (/добав|хочу|куп|возьм|в корзин/.test(low)) {
    const p = findProduct(products, low);
    if (!p) return { reply: 'Какой именно товар добавить? У нас есть розы, тюльпаны и пионы.', cart: session.cart };
    const qty = parseQty(low);
    const existing = session.cart.find((x) => x.product_id === p.id);
    if (existing) existing.qty += qty;
    else session.cart.push({ product_id: p.id, name: p.name, price: Number(p.price), qty });
    return { reply: `Добавил: ${p.name} × ${qty}. В корзине на ${money(cartTotal(session.cart))}. Ещё что-нибудь или «оформить заказ»?`, cart: session.cart };
  }

  // фильтр по цене / рекомендуемые / поиск
  const featured = /рекоменд|популярн|лучш|хит/.test(low);
  const priceM = low.match(/до\s*(\d+(?:[.,]\d+)?)/);
  const maxPrice = priceM ? parseFloat(priceM[1].replace(',', '.')) : undefined;
  const named = findProduct(products, low);
  if (featured || maxPrice !== undefined || named) {
    let res = shop.filterProducts(products, {
      featured_only: featured,
      max_price: maxPrice,
      search: named ? named.name : undefined,
    });
    if (!res.length) return { reply: 'По такому запросу ничего не нашлось. Показать весь каталог?', cart: session.cart };
    return { reply: catalogReply(res), cart: session.cart };
  }

  // каталог по умолчанию
  if (/каталог|покажи|ассортимент|товар|цвет|что есть|выбор/.test(low)) {
    return { reply: catalogReply(products), cart: session.cart };
  }

  return { reply: 'Не совсем понял. Спросите «покажи каталог», «добавьте розу» или «оформить заказ».', cart: session.cart };
}

module.exports = { handle };
