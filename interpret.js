// interpret.js — детерминированная сводка по интеграциям (фолбэк без ключа).
const payment = require('./payment');
const embeddings = require('./embeddings');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  if (/плат|payment|stripe|оплат/.test(low)) {
    return { reply: `Провайдер платежей: ${payment.name}. ${payment.name === 'stripe' ? 'Активен реальный Stripe (STRIPE_SECRET_KEY).' : 'Детерминированный mock — задайте STRIPE_SECRET_KEY для реального Stripe.'}`, engine: 'rules' };
  }
  if (/эмбед|embed|voyage|вектор|поиск/.test(low)) {
    return { reply: `Провайдер эмбеддингов: ${embeddings.provider.name} (модель ${embeddings.provider.model}). ${embeddings.provider.name === 'voyage' ? 'Активен реальный Voyage.' : 'Детерминированный mock — задайте VOYAGE_API_KEY для Voyage.'}`, engine: 'rules' };
  }
  return { reply: `Интеграции: платежи=${payment.name}, эмбеддинги=${embeddings.provider.name}. Оба через адаптеры: реальный провайдер при наличии ключа, иначе mock.`, engine: 'rules' };
}
module.exports = { ask };
