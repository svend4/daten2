// smoke.mjs — реальные HTTP-проверки пакта поведения через границу процессов.
// Поднимаем два mock-агента: «хороший» (удовлетворяет пакт) и «регрессировавший»
// (ломает refuses-absurd — как после неудачной смены модели). Проверяем: пакт держится
// на хорошем, ловит нарушение на плохом, детектит регрессию против baseline,
// детерминирован, и всё это работает по HTTP через server.js.
import http from 'node:http';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const runner = require('../runner');
const app = require('../server');

let passed = 0;
const ok = (c, m) => { assert.ok(c, m); console.log('  ✓', m); passed++; };

// --- mock-агенты магазина (chat-контракт POST /api/chat {message} → {reply}) ---
function reply(message, { regressed } = {}) {
  const m = String(message).toLowerCase();
  if (m.includes('скидк')) {
    // абсурдный запрос — точка расхождения хорошего и регрессировавшего агента
    return regressed
      ? 'Готово! Оформил 1000000 роз со скидкой 100%.'
      : 'Извините, такую скидку предоставить не могу — это нереально. Есть реальные букеты из каталога.';
  }
  if (m.includes('стоит') || m.includes('цена') || m.includes('почём') || m.includes('почем')) return 'Роза стоит 200 ₽ за штуку, букет — от 1500 ₽.';
  if (m.includes('каталог') || m.includes('ассортимент') || m.includes('есть')) return 'В каталоге: розы, тюльпаны, пионы и готовые букеты.';
  if (m.includes('оформ')) return 'Конечно! На какое имя оформить заказ?';
  return 'Я помогаю с цветами 🌷 Показать каталог магазина?';
}

function mockAgent(opts) {
  const srv = http.createServer((req, res) => {
    if (req.method === 'POST' && req.url === '/api/chat') {
      let body = '';
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        let msg = '';
        try { msg = JSON.parse(body).message || ''; } catch { /* ignore */ }
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ reply: reply(msg, opts) }));
      });
    } else { res.writeHead(404); res.end(); }
  });
  return srv;
}

const listen = (srv) => new Promise((r) => srv.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${srv.address().port}`)));
const post = (base, path, body) => new Promise((resolve, reject) => {
  const data = JSON.stringify(body || {});
  const u = new URL(base + path);
  const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
    (res) => { let b = ''; res.on('data', (c) => (b += c)); res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(b) }); } catch (e) { reject(e); } }); });
  req.on('error', reject); req.end(data);
});

async function main() {
  const good = mockAgent({});
  const bad = mockAgent({ regressed: true });
  const goodBase = await listen(good);
  const badBase = await listen(bad);

  console.log('Пакт держится на корректном агенте:');
  const runGood = await runner.runAll(goodBase);
  ok(runGood.allHold, `все ${runGood.total} ожиданий держатся (held=${runGood.held})`);
  ok(runGood.results.every((r) => r.tested > r.inputs?.length || r.tested >= 6 || r.tested > 0), 'каждое ожидание проверено на семействе формулировок');
  ok(runGood.byCat.safety && runGood.byCat.safety.held === runGood.byCat.safety.total, 'категория safety полностью зелёная');

  console.log('Пакт ловит нарушение на регрессировавшем агенте:');
  const runBad = await runner.runAll(badBase);
  ok(!runBad.allHold, `пакт не держится (held=${runBad.held}/${runBad.total})`);
  const brokeAbsurd = runBad.results.find((r) => r.id === 'refuses-absurd');
  ok(brokeAbsurd && !brokeAbsurd.ok, 'сломано именно refuses-absurd');
  ok(/100|готово|оформил|запрещённое/i.test(brokeAbsurd.reason + ' ' + (brokeAbsurd.reply || '')), 'причина указывает на абсурдный ответ');

  console.log('Регрессия детектится против baseline:');
  const cmp = runner.compare(runBad, runGood);
  ok(cmp.hasBaseline, 'baseline учтён');
  ok(cmp.regressions.some((r) => r.id === 'refuses-absurd'), 'refuses-absurd помечен как регрессия (держался → упал)');
  const cmpSelf = runner.compare(runGood, runGood);
  ok(cmpSelf.regressions.length === 0, 'нет ложных регрессий хорошего против самого себя');

  console.log('Детерминизм:');
  const again = await runner.runAll(goodBase);
  ok(JSON.stringify(again.results.map((r) => [r.id, r.ok])) === JSON.stringify(runGood.results.map((r) => [r.id, r.ok])), 'повторный прогон даёт тот же вердикт');

  console.log('HTTP через server.js:');
  const api = await new Promise((r) => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  const apiBase = `http://127.0.0.1:${api.address().port}`;
  const vGood = await post(apiBase, '/api/verify', { agentUrl: goodBase });
  ok(vGood.status === 200 && vGood.body.allHold, 'POST /api/verify на хорошем агенте → allHold');
  const base = await post(apiBase, '/api/baseline', {});
  ok(base.status === 200 && base.body.held === vGood.body.held, 'POST /api/baseline фиксирует прогон');
  const vBad = await post(apiBase, '/api/verify', { agentUrl: badBase });
  ok(vBad.status === 200 && !vBad.body.allHold, 'POST /api/verify на плохом агенте → пакт падает');
  ok(vBad.body.compare && vBad.body.compare.regressions.some((r) => r.id === 'refuses-absurd'), 'HTTP-ответ содержит регрессию refuses-absurd против baseline');
  const askBad = await post(apiBase, '/api/ask', { message: 'какие регрессии при смене модели?' });
  ok(askBad.status === 200 && /refuses-absurd|регресс/i.test(askBad.body.reply), '/api/ask объясняет регрессию словами');

  good.close(); bad.close(); api.close();
  console.log(`\nВсе проверки пройдены (${passed}).`);
}

main().catch((e) => { console.error('ПРОВАЛ:', e); process.exit(1); });
