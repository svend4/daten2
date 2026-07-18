// test/smoke.mjs — проверка семантического поиска на детерминированном энкодере.
// Индексирует mock-каталог через контракт и проверяет ранжирование по смыслу:
// аромат+стойкость, бюджет+яркость, романтика, а также «похожие товары».
import http from 'node:http';

delete process.env.ANTHROPIC_API_KEY; // гарантируем детерминированный энкодер

const CATALOG = [
  { id: 1, name: 'Красная роза',   price: 1.5, currency: 'EUR', is_featured: true,  description: 'Ароматная классическая роза, стоит долго' },
  { id: 2, name: 'Жёлтый тюльпан', price: 0.8, currency: 'EUR', is_featured: false, description: 'Яркий весенний тюльпан без запаха' },
  { id: 3, name: 'Пион',           price: 2.2, currency: 'EUR', is_featured: true,  description: 'Пышный ароматный пион' },
  { id: 4, name: 'Гвоздика',       price: 1.0, currency: 'EUR', is_featured: false, description: 'Очень стойкая, стоит до трёх недель' },
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
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const get = async (p) => (await fetch(base + p)).json();
  const search = async (query) => (await fetch(base + '/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, top: 6 }) })).json();

  console.log('индексация:');
  const idx = await (await fetch(base + '/api/index', { method: 'POST' })).json();
  check('проиндексированы 4 товара', idx.indexed === 4);
  const h = await get('/api/health');
  check('движок rule-based', h.engine === 'rules');
  const axes = await get('/api/axes');
  check('оси доступны', Array.isArray(axes.axes) && axes.axes.some((a) => a.key === 'fragrance'));

  console.log('семантический поиск:');
  const q1 = await search('цветы с приятным запахом, которые долго стоят');
  check('q1: активны оси аромат+стойкость', q1.axes.fragrance > 0 && q1.axes.longevity > 0);
  check('q1: роза на 1-м месте', q1.results[0].name === 'Красная роза');
  check('q1: у розы совпали аромат и стойкость', q1.results[0].matched.includes('аромат') && q1.results[0].matched.includes('стойкость'));
  const rankTulip1 = q1.results.findIndex((r) => r.name === 'Жёлтый тюльпан');
  check('q1: тюльпан без запаха ниже розы', rankTulip1 > 0);

  const q2 = await search('что-нибудь недорогое и яркое');
  check('q2: активны оси бюджет+яркость', q2.axes.affordability > 0 && q2.axes.brightness > 0);
  check('q2: самый дешёвый и яркий тюльпан — первый', q2.results[0].name === 'Жёлтый тюльпан');

  const q3 = await search('романтический букет девушке');
  check('q3: активна ось романтика', q3.axes.romance > 0);
  check('q3: роза — первая', q3.results[0].name === 'Красная роза');

  const q4 = await search('стойкие цветы, которые не вянут неделями');
  check('q4: активна ось стойкости', q4.axes.longevity > 0);
  check('q4: гвоздика в топ-2 (самая стойкая)', q4.results.slice(0, 2).some((r) => r.name === 'Гвоздика'));

  console.log('рекомендации (похожие):');
  const sim = await get('/api/similar/1?top=3');
  check('похожие на розу найдены', Array.isArray(sim.results) && sim.results.length === 3);
  check('роза не рекомендует саму себя', !sim.results.some((r) => r.id === 1));
  check('похожие отсортированы по близости', sim.results[0].score >= sim.results[sim.results.length - 1].score);

  console.log('фолбэк по названию:');
  const q5 = await search('пион');
  check('поиск по названию находит пион', q5.results.some((r) => r.name === 'Пион'));

  srv.close(); backend.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}

main().catch((e) => { console.error(e); process.exit(1); });
