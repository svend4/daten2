// payment/mock.js — детерминированный mock-провайдер платежей (без ключа/сети).
// Реализует тот же интерфейс, что и Stripe-адаптер: createIntent / confirm / get.
const round2 = (n) => Math.round(n * 100) / 100;
const store = new Map();
let seq = 0;

module.exports = {
  name: 'mock',
  async createIntent(amount, currency, orderNumber) {
    const id = 'pi_mock_' + (++seq);
    const intent = { id, amount: round2(amount), currency: (currency || 'EUR').toUpperCase(), order_number: orderNumber || null, status: 'requires_confirmation', provider: 'mock' };
    store.set(id, intent);
    return intent;
  },
  async confirm(id) {
    const i = store.get(id);
    if (!i) throw new Error('интент не найден');
    i.status = 'succeeded';
    return i;
  },
  async get(id) { return store.get(id) || null; },
};
