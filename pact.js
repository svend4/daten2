// pact.js — consumer-driven contract (пакт). Это ожидания ПОТРЕБИТЕЛЯ (фронтенд /
// AI-слой) к любому провайдеру-уровню. Каждый уровень обязан удовлетворить пакт —
// это и есть машинная гарантия взаимозаменяемости. Матчеры — типовые (не значения).
const PRODUCT = { object: { id: 'number', name: 'string', price: 'number' } };
const ORDER = { object: { order_number: 'string', total: 'number' } };

module.exports = {
  consumer: 'flower-shop-frontend',
  provider: 'flower-shop-level',
  interactions: [
    {
      id: 'health', description: 'здоровье уровня',
      request: { method: 'GET', path: '/api/health' },
      response: { status: [200], body: { object: { ok: 'boolean' } } },
    },
    {
      id: 'products', description: 'каталог — массив товаров с id/name/price',
      request: { method: 'GET', path: '/api/products' },
      response: { status: [200], body: { array: PRODUCT } },
    },
    {
      id: 'create-order', description: 'оформление заказа возвращает order_number + total',
      request: { method: 'POST', path: '/api/orders', body: { name: 'CDC-consumer', items: [{ product_id: 1, quantity: 2 }] } },
      response: { status: [200, 201], body: ORDER },
      capture: { orderNumber: 'order_number' }, // токен для следующего взаимодействия
    },
    {
      id: 'get-order', description: 'поиск заказа по выданному токену',
      request: { method: 'GET', path: '/api/orders/{{orderNumber}}' },
      response: { status: [200], body: ORDER },
    },
    {
      id: 'order-privacy', description: 'несуществующий токен → 404 (приватность)',
      request: { method: 'GET', path: '/api/orders/does-not-exist-404' },
      response: { status: [404, 400], body: 'any' },
    },
  ],
};
