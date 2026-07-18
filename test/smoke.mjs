// test/smoke.mjs — проверка дистилляции учитель→ученик (без ключа, без сети).
// Согласие ученика с учителем, детерминизм, экспорт/импорт, инференс, HTTP.
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

delete process.env.ANTHROPIC_API_KEY;

let failures = 0;
const check = (n, ok) => { console.log((ok ? '  ✓ ' : '  ✗ ') + n); if (!ok) failures++; };

async function main() {
  const teacher = require('../teacher.js');
  const dataset = require('../dataset.js');
  const student = require('../student.js');
  const distill = require('../distill.js');

  console.log('данные и учитель:');
  const rows = dataset.generate(400, 7);
  check('датасет сгенерирован', rows.length >= 100 && rows.every((r) => teacher.LABELS.includes(r.label)));
  check('покрыты разные метки', new Set(rows.map((r) => r.label)).size >= 5);
  check('учитель: «оформить заказ» → checkout', teacher.label('оформить заказ') === 'checkout');
  check('учитель: «добавьте розы» → add', teacher.label('добавьте розы') === 'add');

  console.log('дистилляция:');
  const d1 = distill.distill({ n: 1200, seed: 42, epochs: 600, lr: 0.8 });
  check('ученик почти повторяет учителя (согласие ≥ 0.9)', d1.metrics.agreement >= 0.9);
  check('обучение сошлось (loss мал)', d1.metrics.loss < 0.5);

  console.log('детерминизм:');
  const d2 = distill.distill({ n: 1200, seed: 42, epochs: 600, lr: 0.8 });
  check('тот же seed → тот же результат', d1.metrics.agreement === d2.metrics.agreement && JSON.stringify(student.exportModel(d1.model)) === JSON.stringify(student.exportModel(d2.model)));

  console.log('инференс ученика:');
  const clear = { 'привет': 'greet', 'покажи каталог': 'catalog', 'добавьте пионы': 'add', 'оформить заказ': 'checkout', 'что в корзине': 'cart', 'что-нибудь недорогое': 'filter' };
  let hits = 0;
  for (const [text, exp] of Object.entries(clear)) if (student.predict(d1.model, text).label === exp) hits++;
  check('ученик верно классифицирует явные примеры', hits >= 5);
  const p = student.predict(d1.model, 'оформить заказ');
  check('есть уверенность и распределение', p.confidence > 0.3 && p.probs && typeof p.probs.checkout === 'number');

  console.log('экспорт/импорт:');
  const exp = student.exportModel(d1.model);
  const imported = student.importModel(exp);
  check('модель компактна (обрезаны нули)', exp.W.reduce((a, r) => a + r.length, 0) < d1.model.K * d1.model.dim);
  check('импорт даёт те же предсказания', student.predict(imported, 'добавьте розы').label === student.predict(d1.model, 'добавьте розы').label);

  console.log('HTTP:');
  const { default: app } = await import('../server.js');
  const srv = http.createServer(app);
  const port = await new Promise((r) => srv.listen(0, () => r(srv.address().port)));
  const base = `http://localhost:${port}`;
  const post = async (p, b) => (await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).json();

  const h = await (await fetch(base + '/api/health')).json();
  check('health: учитель rules, согласие есть', h.engine === 'rules-teacher' && h.agreement >= 0.9);
  const c = await post('/api/classify', { text: 'хочу купить букет роз' });
  check('classify: ученик + метка учителя', teacher.LABELS.includes(c.label) && teacher.LABELS.includes(c.teacher));
  const m = await (await fetch(base + '/api/model')).json();
  check('экспорт модели через API', Array.isArray(m.model.labels) && m.nonzero_weights > 0);
  const tr = await post('/api/train', { n: 900, epochs: 400, lr: 0.7 });
  check('переобучение через API', typeof tr.agreement === 'number' && tr.agreement >= 0.8);

  srv.close();
  if (failures) { console.error(`\nFAILED: ${failures} проверок не прошли`); process.exit(1); }
  console.log('\nPASSED: все проверки пройдены');
}
main().catch((e) => { console.error(e); process.exit(1); });
