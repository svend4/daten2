// test/smoke.mjs — проверка Vision (детерминированное цветовое ядро).
// PNG-кодек (round-trip), классификация цвета → тип цветка, поиск по фото, авто-теги.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

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
  const png = require('../png.js');
  const vision = require('../vision.js');

  const redPng = png.encodeSolid(16, 16, { r: 200, g: 30, b: 30 });
  const yellowPng = png.encodeSolid(16, 16, { r: 220, g: 200, b: 40 });
  const pinkPng = png.encodeSolid(16, 16, { r: 230, g: 150, b: 180 });

  console.log('PNG-кодек:');
  const dec = png.decode(redPng);
  check('round-trip: размеры сохранены', dec.width === 16 && dec.height === 16);
  check('round-trip: цвет пикселя верный', dec.pixels[0] === 200 && dec.pixels[1] === 30 && dec.pixels[2] === 30);
  let threw = false; try { png.decode(Buffer.from('not an image')); } catch { threw = true; }
  check('не-PNG → ошибка (не падение)', threw);

  console.log('классификация цвета → цветок:');
  const red = vision.analyzeBuffer(redPng);
  check('красный → роза + романтика', red.colorName === 'красный' && red.flowerRoot === 'роз' && red.tags.includes('романтика'));
  const yellow = vision.analyzeBuffer(yellowPng);
  check('жёлтый → тюльпан', yellow.colorName === 'жёлтый' && yellow.flowerRoot === 'тюльпан');
  const pink = vision.analyzeBuffer(pinkPng);
  check('розовый → пион + нежность', pink.colorName === 'розовый' && pink.flowerRoot === 'пион' && pink.tags.includes('нежность'));

  console.log('поиск по фото (сопоставление каталога):');
  const m = vision.matchProducts(red, CATALOG);
  check('красное фото → роза первой', m[0].name === 'Красная роза' && m[0].reasons.length > 0);
  const my = vision.matchProducts(yellow, CATALOG);
  check('жёлтое фото → тюльпан первым', my[0].name === 'Жёлтый тюльпан');

  console.log('HTTP:');
  const bport = await listen(backend);
  process.env.BACKEND_URL = `http://localhost:${bport}`;
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await listen(srv);
  const base = `http://localhost:${port}`;
  const post = async (p, b) => { const r = await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); return { status: r.status, body: await r.json() }; };

  const h = await (await fetch(base + '/api/health')).json();
  check('движок rule-based', h.engine === 'rules');

  const an = await post('/api/analyze', { imageBase64: redPng.toString('base64') });
  check('analyze: описание непустое', an.status === 200 && typeof an.body.description === 'string' && an.body.description.length > 10);

  const sp = await post('/api/search-by-photo', { imageBase64: redPng.toString('base64') });
  check('search-by-photo → роза первой', sp.status === 200 && sp.body.results[0].name === 'Красная роза');

  const tag = await post('/api/autotag', { imageBase64: pinkPng.toString('base64') });
  check('autotag: теги и описание', tag.status === 200 && Array.isArray(tag.body.tags) && tag.body.description.length > 0);

  const bad = await post('/api/analyze', { imageBase64: Buffer.from('nope').toString('base64') });
  check('битый вход → 400, без падения', bad.status === 400 && !!bad.body.error);

  srv.close(); backend.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
