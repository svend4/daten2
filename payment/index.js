// payment/index.js — выбор провайдера платежей: реальный Stripe при STRIPE_SECRET_KEY,
// иначе детерминированный mock. Один интерфейс для остального кода.
module.exports = process.env.STRIPE_SECRET_KEY ? require('./stripe') : require('./mock');
