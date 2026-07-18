// stacks.js — семь стеков-испытуемых с метаданными для отчёта.
// language/storage — для кросс-языкового сравнения; watts — номинальная мощность
// (для метрики эффективности «запросов на ватт»). Настраивается через BENCH_STACKS.
function load() {
  if (process.env.BENCH_STACKS) {
    try { const a = JSON.parse(process.env.BENCH_STACKS); if (Array.isArray(a) && a.length) return a; }
    catch { /* значения по умолчанию */ }
  }
  return [
    { id: 'level1', name: 'L1 · PHP', language: 'PHP 8.2', storage: 'SQLite', watts: 12, url: 'http://localhost:8081' },
    { id: 'level2', name: 'L2 · Flask', language: 'Python 3.12', storage: 'SQLite', watts: 18, url: 'http://localhost:8082' },
    { id: 'level3', name: 'L3 · Django', language: 'Python 3.12', storage: 'SQLite', watts: 20, url: 'http://localhost:8083' },
    { id: 'level4', name: 'L4 · Express', language: 'Node.js 20', storage: 'SQLite', watts: 16, url: 'http://localhost:8084' },
    { id: 'level5', name: 'L5 · React+API', language: 'Python + JS', storage: 'SQLite', watts: 22, url: 'http://localhost:8085' },
    { id: 'level6', name: 'L6 · Next.js', language: 'TypeScript', storage: 'PostgreSQL', watts: 30, url: 'http://localhost:8086' },
    { id: 'level7', name: 'L7 · Microservices', language: 'Node + Python', storage: 'PostgreSQL', watts: 45, url: 'http://localhost:8087' },
  ];
}
module.exports = { stacks: load() };
