// payment-service — общий сервис оплаты за роутером.
// Подключаемый провайдер (mock/stripe). Хранилище платежей — in-memory (демо).
const express = require('express');
const crypto = require('crypto');

const app = express();
app.use(express.json());

// providerRef -> { orderNumber, amount, currency, status }
const payments = new Map();

// --- подключаемый провайдер (тот же интерфейс, что и реальный Stripe) ---
const provider = {
  name: process.env.PAYMENT_PROVIDER || 'mock',
  createIntent(amount, currency) {
    const ref = 'pi_' + this.name + '_' + crypto.randomUUID().replace(/-/g, '');
    return { providerRef: ref, clientSecret: ref + '_secret', amount, currency };
  },
  confirm(ref) {
    // В реальном провайдере — сверка с платёжным шлюзом.
    return { providerRef: ref, status: ref.startsWith('pi_') ? 'SUCCEEDED' : 'FAILED' };
  },
};

app.get('/health', (_, res) => res.json({ ok: true, service: 'payment', provider: provider.name }));

// создать намерение оплаты
app.post('/api/payments/intent', (req, res) => {
  const orderNumber = req.body?.order_number;
  const amount = Number(req.body?.amount);
  const currency = req.body?.currency || 'EUR';
  if (!orderNumber || !(amount >= 0)) {
    return res.status(400).json({ error: 'order_number и amount обязательны' });
  }
  const intent = provider.createIntent(amount, currency);
  payments.set(intent.providerRef, { orderNumber, amount, currency, status: 'REQUIRES_CONFIRMATION' });
  res.status(201).json({
    provider_ref: intent.providerRef,
    client_secret: intent.clientSecret,
    amount, currency,
  });
});

// подтвердить платёж (аналог webhook)
app.post('/api/payments/confirm', (req, res) => {
  const ref = req.body?.provider_ref;
  const payment = payments.get(ref);
  if (!payment) return res.status(404).json({ error: 'платёж не найден' });
  const result = provider.confirm(ref);
  payment.status = result.status;
  if (result.status !== 'SUCCEEDED') {
    return res.status(402).json({ error: 'платёж отклонён', status: 'FAILED' });
  }
  res.json({ order_number: payment.orderNumber, status: 'SUCCEEDED', amount: payment.amount });
});

// статус оплаты по заказу
app.get('/api/payments/:orderNumber', (req, res) => {
  for (const p of payments.values()) {
    if (p.orderNumber === req.params.orderNumber) {
      return res.json({ order_number: p.orderNumber, status: p.status, amount: p.amount });
    }
  }
  res.status(404).json({ error: 'платёж не найден' });
});

const PORT = process.env.PORT || 8092;
if (require.main === module) {
  app.listen(PORT, () => console.log(`payment-service on :${PORT} (provider ${provider.name})`));
}
module.exports = app;
