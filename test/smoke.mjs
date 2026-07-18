// test/smoke.mjs — проверка RAG + память (детерминированный движок).
// Извлечение релевантных чанков, память клиента, персонализированные рекомендации.
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;
process.env.DATA_DIR = path.join(os.tmpdir(), 'rag-smoke-' + process.pid);

const CATALOG = [
  { id: 1, name: 'Красная роза', price: 1.5, currency: 'EUR', is_featured: true, stock: 40 },
  { id: 2, name: 'Жёлтый тюльпан', price: 0.8, currency: 'EUR', is_featured: false, stock: 60 },
  { id: 3, name: 'Пион', price: 2.2, currency: 'EUR', is_featured: true, stock: 25 },
];
const backend = http.createServer((req, res) => {
  if (req.url === '/api/products') { res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify(CATALOG)); }
  res.writeHead(404); res.end('{}');
});
const listen = (s) => new Promise((r) => s.listen(0, () => r(s.address().port)));

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const retriever = require('../retriever.js');

  console.log('извлечение (retrieval):');
  const care = retriever.retrieve('как ухаживать за розами чтобы дольше стояли');
  check('уход за розами → care-rose первым', care[0] && care[0].id === 'care-rose');
  const deliv = retriever.retrieve('когда будет доставка сегодня');
  check('доставка → delivery', deliv.some((s) => s.id === 'delivery'));
  const ret = retriever.retrieve('хочу вернуть повреждённый букет');
  check('возврат → returns', ret.some((s) => s.id === 'returns'));
  const none = retriever.retrieve('квантовая хромодинамика адронов');
  check('нерелевантный запрос → пусто', none.length === 0);

  // HTTP
  const bport = await listen(backend);
  process.env.BACKEND_URL = `http://localhost:${bport}`;
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const get = async (p) => (await fetch(base + p)).json();
  const post = async (p, b) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })).json();

  console.log('HTTP RAG:');
  const h = await get('/api/health');
  check('движок rule-based, база загружена', h.engine === 'rules' && h.kb >= 8);
  const a1 = await post('/api/ask', { customerId: 'u1', question: 'сколько стоят розы в вазе и как ухаживать' });
  check('ответ по базе непустой', typeof a1.answer === 'string' && a1.answer.length > 10);
  check('источники приложены (care-rose первым)', Array.isArray(a1.sources) && a1.sources.length > 0 && a1.sources[0].id === 'care-rose');
  const aNone = await post('/api/ask', { customerId: 'u1', question: 'квантовая хромодинамика' });
  check('нет в базе → честный отказ', /не нашёл/i.test(aNone.answer) && aNone.sources.length === 0);

  console.log('память:');
  await post('/api/memory/u2', { preferences: { favorites: ['Красная роза'], occasions: ['маме'], budget: 2.5 } });
  const mem = await get('/api/memory/u2');
  check('предпочтения сохранены', mem.preferences.favorites.includes('Красная роза') && mem.preferences.budget === 2.5);
  const a2 = await post('/api/ask', { customerId: 'u2', question: 'посоветуйте что-нибудь' });
  check('ответ учитывает память (любимое)', /Красная роза/.test(a2.answer));
  const memAfter = await get('/api/memory/u2');
  check('вопросы пишутся в историю', memAfter.history.length >= 1);

  console.log('персонализированные рекомендации:');
  const rec = await post('/api/recommend', { customerId: 'u2' });
  check('рекомендации построены', Array.isArray(rec.recommendations) && rec.recommendations.length > 0);
  check('любимое (роза) вверху', rec.recommendations[0].name === 'Красная роза' && rec.recommendations[0].reasons.includes('любимый'));
  check('повод «маме» → пион отмечен', rec.recommendations.some((r) => r.name === 'Пион' && r.reasons.includes('под повод')));
  const recAnon = await post('/api/recommend', { customerId: 'nobody' });
  check('без памяти — тоже что-то советует (featured)', recAnon.recommendations.length > 0);

  srv.close(); backend.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
