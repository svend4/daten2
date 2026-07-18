// test/smoke.mjs — проверка ИИ-управляющего на детерминированном ядре.
// (1) интеграция: снимок каталога через контракт (mock-бэкенд);
// (2) аналитика: спрос, прогноз, дозаказ, цена, аномалии на синтетическом ряде;
// (3) HTTP: /api/report и /api/ask (движок rules, без ANTHROPIC_API_KEY).
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';

const DAY = 86_400_000;

// изолируем окружение до импорта сервера
process.env.DATA_DIR = path.join(os.tmpdir(), 'ai-manager-smoke-' + process.pid);
delete process.env.ANTHROPIC_API_KEY;

// --- mock-бэкенд контракта ---------------------------------------------------
let CATALOG = [
  { id: 1, name: 'Красная роза', price: 1.5, stock: 40, is_featured: true },
  { id: 2, name: 'Жёлтый тюльпан', price: 0.8, stock: 60, is_featured: false },
];
const backend = http.createServer((req, res) => {
  if (req.url === '/api/products') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify(CATALOG)); }
  res.writeHead(404); res.end('{}');
});
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const bport = await listen(backend);
  process.env.BACKEND_URL = `http://localhost:${bport}`;

  const store = (await import('../store.js')).default || (await import('../store.js'));
  const analyticsMod = await import('../analytics.js');
  const { default: app } = await import('../server.js');

  store.reset();

  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const get = async (p) => (await fetch(base + p)).json();
  const post = async (p, b) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined })).json();

  // (1) интеграция: живой снимок через контракт
  console.log('интеграция (снимок через контракт):');
  const s1 = await post('/api/snapshot');
  check('снимок записан', s1.ok === true && s1.snapshots === 1);
  const h = await get('/api/health');
  check('движок rule-based', h.engine === 'rules');
  check('health видит снимок', h.snapshots === 1);
  check('backend виден', h.backend === process.env.BACKEND_URL);

  // (2) синтетический ряд: 10 суточных снимков
  console.log('аналитика (синтетический ряд):');
  store.reset();
  // роза: спрос 6/сут → дозаказ + рост цены; тюльпан: без продаж → скидка + смена цены;
  // пион: базово 2/сут, затем всплеск 20 → аномалия spike.
  const rose = [64, 58, 52, 46, 40, 34, 28, 22, 16, 10];
  const tulip = [60, 60, 60, 60, 60, 60, 60, 60, 60, 60];
  const tulipPrice = [0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.9];
  const peony = [40, 38, 36, 34, 32, 30, 28, 26, 24, 4];
  for (let i = 0; i < 10; i++) {
    store.record([
      { id: 1, name: 'Красная роза', price: 1.5, stock: rose[i], is_featured: true },
      { id: 2, name: 'Жёлтый тюльпан', price: tulipPrice[i], stock: tulip[i], is_featured: false },
      { id: 3, name: 'Пион', price: 2.2, stock: peony[i], is_featured: true },
    ], i * DAY);
  }

  const rep = await get('/api/report');
  const byName = (n) => rep.products.find((p) => p.name === n);
  const R = byName('Красная роза'), T = byName('Жёлтый тюльпан'), P = byName('Пион');

  check('роза: спрос ≈6/сут', R.dailyRate === 6);
  check('роза: прогноз < срока поставки', R.daysToStockout !== null && R.daysToStockout < 3);
  check('роза: нужен дозаказ', R.needsReorder === true && R.reorderQty > 0);
  check('роза: цена — поднять', R.price_suggestion.action === 'raise');
  check('дозаказ в отчёте содержит розу', rep.reorders.some((x) => x.name === 'Красная роза'));

  check('тюльпан: спрос 0', T.dailyRate === 0);
  check('тюльпан: цена — скидка', T.price_suggestion.action === 'discount');
  check('тюльпан: аномалия смены цены', T.anomalies.some((a) => a.type === 'price-change'));
  check('тюльпан: не расходуется (∞)', T.daysToStockout === null);

  check('пион: аномалия-всплеск', P.anomalies.some((a) => a.type === 'spike'));
  check('всплеск попал в сводку аномалий', rep.anomalies.some((a) => a.id === 3 && a.type === 'spike'));

  // (3) детерминированный Q&A через /api/ask
  console.log('Q&A (движок rules):');
  const qReorder = await post('/api/ask', { sessionId: 't', message: 'что дозаказать?' });
  check('дозаказ: упомянута роза', /Красная роза/.test(qReorder.reply) && qReorder.engine === 'rules');
  const qAnom = await post('/api/ask', { sessionId: 't', message: 'есть аномалии?' });
  check('аномалии: упомянут пион', /Пион/.test(qAnom.reply));
  const qPrice = await post('/api/ask', { sessionId: 't', message: 'что с ценами?' });
  check('цены: есть подсказка', /снизить|поднять/.test(qPrice.reply));
  const qFc = await post('/api/ask', { sessionId: 't', message: 'прогноз по остаткам' });
  check('прогноз: перечислены товары', /Красная роза/.test(qFc.reply) && /Пион/.test(qFc.reply));

  srv.close(); backend.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}

main().catch((e) => { console.error(e); process.exit(1); });
