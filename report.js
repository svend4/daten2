// report.js — генератор ПУБЛИКУЕМОГО отчёта (Markdown/HTML) из результатов бенчмарка.
// Чистая функция (результаты + метаданные → строка): структура детерминирована,
// поэтому отчёт воспроизводим и годится как исследовательский артефакт.
const cell = (v) => (v == null ? '—' : v);

function markdown(results, meta = {}) {
  const { endpoint = '/api/products', requests = 100, concurrency = 10, at = 'н/д', warmup = 5, repo = 'svend4/daten2' } = meta;
  const alive = results.filter((r) => r.alive);
  const winner = alive[0];
  const greenest = [...alive].filter((r) => r.rps_per_watt != null).sort((a, b) => b.rps_per_watt - a.rps_per_watt)[0];

  const lines = [];
  lines.push('# Полиглот-бенчмарк: семь стеков за единым контрактом');
  lines.push('');
  lines.push(`> Кросс-языковое перф-исследование одного и того же магазина цветов, реализованного на семи стеках (PHP → микросервисы), которые говорят на **едином REST-контракте** и потому сравнимы «в лоб». Отчёт сгенерирован автоматически и воспроизводим.`);
  lines.push('');
  lines.push(`**Дата прогона:** ${at} · **Стеков:** ${results.length} (живых: ${alive.length}) · **Репозиторий:** \`${repo}\``);
  lines.push('');
  lines.push('## Методология');
  lines.push('');
  lines.push(`- **Эндпоинт:** \`GET ${endpoint}\` (только чтение — без побочных эффектов).`);
  lines.push(`- **Нагрузка:** ${requests} запросов при параллелизме ${concurrency}; прогрев ${warmup} запросов (в метрики не входит).`);
  lines.push(`- **Метрики:** латентность p50/p95/p99 (мс), пропускная способность (успешных запросов/с), надёжность (доля 2xx), эффективность (rps на ватт номинальной мощности).`);
  lines.push(`- **Условие сравнимости:** все стеки реализуют один контракт и одинаковую каноническую схему/сид — различается только реализация.`);
  lines.push('');
  lines.push('## Результаты');
  lines.push('');
  lines.push('| # | Стек | Язык | Хранилище | p50 | p95 | p99 | rps | success | rps/Вт |');
  lines.push('|---|------|------|-----------|----:|----:|----:|----:|:------:|-----:|');
  for (const r of results) {
    if (!r.alive) { lines.push(`| — | ${r.name} | ${r.language} | ${r.storage} | offline | — | — | — | — | — |`); continue; }
    lines.push(`| ${r.rank} | ${r.name} | ${r.language} | ${r.storage} | ${cell(r.p50)} | ${cell(r.p95)} | ${cell(r.p99)} | ${cell(r.rps)} | ${Math.round((r.success_ratio || 0) * 100)}% | ${cell(r.rps_per_watt)} |`);
  }
  lines.push('');
  lines.push('## Выводы');
  lines.push('');
  if (winner) lines.push(`- **Самый быстрый (p95):** ${winner.name} — p95 ${cell(winner.p95)} мс, ${cell(winner.rps)} rps.`);
  if (greenest) lines.push(`- **Самый эффективный (rps/Вт):** ${greenest.name} — ${cell(greenest.rps_per_watt)} запросов на ватт.`);
  if (alive.length >= 2) lines.push(`- **Разброс p95:** от ${cell(alive[0].p95)} до ${cell(alive[alive.length - 1].p95)} мс между стеками при идентичном контракте.`);
  const offline = results.filter((r) => !r.alive);
  if (offline.length) lines.push(`- **Offline:** ${offline.map((r) => r.name).join(', ')} (не участвовали в прогоне).`);
  lines.push('');
  lines.push('## Воспроизводимость');
  lines.push('');
  lines.push('```bash');
  lines.push('# поднять стеки (единый стенд) и прогнать бенчмарк:');
  lines.push('docker compose up --build');
  lines.push(`curl -XPOST localhost:8100/api/run -H 'Content-Type: application/json' \\`);
  lines.push(`  -d '{"endpoint":"${endpoint}","requests":${requests},"concurrency":${concurrency}}'`);
  lines.push('curl localhost:8100/api/report.md   # этот отчёт');
  lines.push('```');
  lines.push('');
  lines.push('_Отчёт сгенерирован полиглот-бенчмарком автоматически. Значения латентности зависят от железа; структура и методология воспроизводимы._');
  return lines.join('\n');
}

function html(results, meta) {
  const md = markdown(results, meta);
  // минимальный рендер: экранируем и оборачиваем в <pre> для надёжной автономности
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return `<!doctype html><meta charset="utf-8"><title>Полиглот-бенчмарк</title><body style="font-family:ui-monospace,monospace;max-width:820px;margin:2rem auto;padding:0 1rem;line-height:1.5"><pre style="white-space:pre-wrap">${esc(md)}</pre></body>`;
}

module.exports = { markdown, html };
