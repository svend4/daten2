// payment/stripe.js — реальный провайдер платежей через Stripe REST API (raw HTTPS).
// Активен при STRIPE_SECRET_KEY. Тот же интерфейс, что и mock. Суммы — в минорных
// единицах (центах); конвертируем евро → центы.
const KEY = process.env.STRIPE_SECRET_KEY || '';
const BASE = 'https://api.stripe.com/v1';

async function call(method, path, form) {
  const init = { method, headers: { Authorization: 'Bearer ' + KEY, 'Content-Type': 'application/x-www-form-urlencoded' } };
  if (form) init.body = new URLSearchParams(form).toString();
  const r = await fetch(BASE + path, init);
  const body = await r.json();
  if (!r.ok) throw new Error(body && body.error ? body.error.message : 'Stripe HTTP ' + r.status);
  return body;
}
const map = (pi) => ({ id: pi.id, amount: pi.amount / 100, currency: (pi.currency || 'eur').toUpperCase(), order_number: pi.metadata && pi.metadata.order_number, status: pi.status, provider: 'stripe' });

module.exports = {
  name: 'stripe',
  async createIntent(amount, currency, orderNumber) {
    const pi = await call('POST', '/payment_intents', {
      amount: Math.round(Number(amount) * 100),
      currency: (currency || 'EUR').toLowerCase(),
      'metadata[order_number]': orderNumber || '',
      'automatic_payment_methods[enabled]': 'true',
    });
    return map(pi);
  },
  async confirm(id) { return map(await call('POST', `/payment_intents/${id}/confirm`, { payment_method: 'pm_card_visa' })); },
  async get(id) { return map(await call('GET', `/payment_intents/${id}`)); },
};
