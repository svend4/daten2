// spec.js — машинная спецификация единого контракта (операции + типы).
// Источник и для codegen (типизированные клиенты), и для CDC-пакта.
module.exports = {
  title: 'Flower Shop Unified Contract',
  version: '1.0.0',
  operations: [
    { name: 'health', method: 'GET', path: '/api/health', returns: 'Health' },
    { name: 'listProducts', method: 'GET', path: '/api/products', returns: 'Product[]' },
    { name: 'createOrder', method: 'POST', path: '/api/orders', body: 'OrderInput', returns: 'Order' },
    { name: 'getOrder', method: 'GET', path: '/api/orders/{orderNumber}', params: ['orderNumber'], returns: 'Order' },
  ],
  types: {
    Health: { ok: 'boolean' },
    Product: { id: 'number', name: 'string', price: 'number', currency: 'string?', stock: 'number?', is_featured: 'boolean?' },
    OrderInput: { name: 'string', items: 'OrderItem[]' },
    OrderItem: { product_id: 'number', quantity: 'number' },
    Order: { order_number: 'string', total: 'number' },
  },
};
