// interpret.js — детерминированная интерпретация результатов (фолбэк без LLM-ключа).
const store = require('./store');
const bench = require('./bench');

const ms = (n) => (n == null ? '—' : n + ' мс');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const run = store.get();
  if (!run) return { reply: 'Бенчмарк ещё не запускался — нажмите «Прогнать бенчмарк».', engine: 'rules' };
  const ranked = bench.rank(run.results);
  const live = ranked.filter((r) => r.alive);

  // проблемные / надёжность
  if (/проблем|надёжн|надежн|ошибк|сбой|offline|недоступ|падает/.test(low)) {
    const bad = run.results.filter((r) => !r.alive || r.success_ratio < 1);
    if (!bad.length) return { reply: 'Все стеки живы и без ошибок (success 100%).', engine: 'rules' };
    return { reply: 'Проблемные стеки:\n' + bad.map((r) => `• ${r.name}: ${r.alive ? `success ${Math.round(r.success_ratio * 100)}%` : 'offline'}`).join('\n'), engine: 'rules' };
  }
  // пропускная способность
  if (/пропуск|throughput|rps|нагрузк|запрос.*с/.test(low)) {
    const byTp = [...live].sort((a, b) => b.throughput_rps - a.throughput_rps);
    return { reply: 'Пропускная способность:\n' + byTp.map((r) => `• ${r.name}: ${r.throughput_rps} rps`).join('\n'), engine: 'rules' };
  }
  // самый медленный
  if (/медлен|худш|хуже|тормоз|slow/.test(low)) {
    const slow = [...live].reverse();
    return { reply: 'От медленных к быстрым (по p95):\n' + slow.map((r) => `• ${r.name}: p95 ${ms(r.latency_ms.p95)}`).join('\n'), engine: 'rules' };
  }
  // сравнение / таблица
  if (/сравн|таблиц|все|список|итог/.test(low)) {
    const lines = ranked.map((r, i) => r.alive
      ? `${i + 1}. ${r.name}: p50 ${ms(r.latency_ms.p50)}, p95 ${ms(r.latency_ms.p95)}, ${r.throughput_rps} rps, success ${Math.round(r.success_ratio * 100)}%`
      : `—. ${r.name}: offline`);
    return { reply: 'Рейтинг стеков:\n' + lines.join('\n'), engine: 'rules' };
  }
  // по умолчанию — самый быстрый + сводка
  if (!live.length) return { reply: 'Ни один стек не ответил — проверьте, запущены ли уровни.', engine: 'rules' };
  const top = live[0];
  const parts = [`Самый быстрый стек — «${top.name}»: p95 ${ms(top.latency_ms.p95)}, ${top.throughput_rps} rps, success ${Math.round(top.success_ratio * 100)}%.`];
  if (live[1]) parts.push(`Следом «${live[1].name}» (p95 ${ms(live[1].latency_ms.p95)}).`);
  const offline = run.results.filter((r) => !r.alive);
  if (offline.length) parts.push(`Offline: ${offline.map((r) => r.name).join(', ')}.`);
  parts.push(`Прогон: ${top.requests} запросов на стек.`);
  return { reply: parts.join(' '), engine: 'rules' };
}

module.exports = { ask };
