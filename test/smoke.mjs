// test/smoke.mjs — проверка интеграций на mock-провайдерах (без ключей/сети).
// Платежи (intent→confirm→status), детерминированные эмбеддинги, similarity, выбор провайдера.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;
delete process.env.STRIPE_SECRET_KEY;
delete process.env.VOYAGE_API_KEY;

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const payment = require('../payment/index.js');
  const embeddings = require('../embeddings/index.js');

  console.log('выбор провайдера (без ключей → mock):');
  check('платежи → mock', payment.name === 'mock');
  check('эмбеддинги → mock', embeddings.provider.name === 'mock');

  console.log('платежи (mock):');
  const intent = await payment.createIntent(12.5, 'eur', 'ORD-1');
  check('intent создан (requires_confirmation)', /^pi_mock_/.test(intent.id) && intent.status === 'requires_confirmation');
  check('сумма и валюта сохранены', intent.amount === 12.5 && intent.currency === 'EUR' && intent.order_number === 'ORD-1');
  const conf = await payment.confirm(intent.id);
  check('confirm → succeeded', conf.status === 'succeeded');
  const got = await payment.get(intent.id);
  check('статус читается по id', got && got.status === 'succeeded');
  let threw = false; try { await payment.confirm('pi_nope'); } catch { threw = true; }
  check('неизвестный intent → ошибка', threw);

  console.log('эмбеддинги (mock):');
  const [v1] = await embeddings.provider.embed(['красная роза']);
  const [v2] = await embeddings.provider.embed(['красная роза']);
  check('детерминизм: тот же текст → тот же вектор', JSON.stringify(v1) === JSON.stringify(v2));
  check('фиксированная размерность', v1.length === embeddings.provider.dim && v1.length > 0);
  check('вектор L2-нормирован (~1)', Math.abs(Math.sqrt(v1.reduce((s, x) => s + x * x, 0)) - 1) < 1e-3);

  console.log('семантическая близость (cosine):');
  const ranked = await embeddings.rank('красная роза для романтики', ['красная роза классическая', 'жёлтый тюльпан весенний', 'офисный степлер']);
  check('релевантный документ вверху', ranked[0].doc === 'красная роза классическая');
  check('нерелевантный внизу с низким score', ranked[ranked.length - 1].doc === 'офисный степлер' && ranked[ranked.length - 1].score < ranked[0].score);

  console.log('HTTP:');
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await new Promise((r) => srv.listen(0, () => r(srv.address().port)));
  const base = `http://localhost:${port}`;
  const post = async (p, b) => { const r = await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }); return { status: r.status, body: await r.json() }; };

  const h = await (await fetch(base + '/api/health')).json();
  check('health: провайдеры mock', h.payment === 'mock' && h.embeddings === 'mock');
  const prov = await (await fetch(base + '/api/providers')).json();
  check('providers: real=false для обоих', prov.payment.real === false && prov.embeddings.real === false);

  const pi = await post('/api/payments/intent', { amount: 5, currency: 'EUR', orderNumber: 'ORD-9' });
  check('HTTP intent создан', pi.status === 201 && /^pi_mock_/.test(pi.body.id));
  const pc = await post('/api/payments/confirm', { intentId: pi.body.id });
  check('HTTP confirm → succeeded', pc.body.status === 'succeeded');
  const bad = await post('/api/payments/intent', { amount: 0 });
  check('HTTP: amount 0 → 400', bad.status === 400);

  const emb = await post('/api/embed', { texts: ['розы', 'тюльпаны'] });
  check('HTTP embed: 2 вектора нужной размерности', emb.body.vectors.length === 2 && emb.body.dim === embeddings.provider.dim);
  const sim = await post('/api/similarity', { query: 'красные розы', docs: ['красные розы букет', 'канцелярия'] });
  check('HTTP similarity: релевантный первый', sim.body.results[0].doc === 'красные розы букет');
  const q = await post('/api/ask', { message: 'какой провайдер платежей?' });
  check('ask (rules) про провайдера', /mock|stripe|платеж/i.test(q.body.reply) && q.body.engine === 'rules');

  srv.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
