// registry.js — кандидаты-бэкенды роутера (уровни L1…L7 или их деплои).
// Все говорят на едином контракте; отличаются латентностью, стоимостью, нагрузкой.
// Настраивается через ROUTER_BACKENDS (JSON) — иначе локальные значения по умолчанию.
function load() {
  if (process.env.ROUTER_BACKENDS) {
    try { const a = JSON.parse(process.env.ROUTER_BACKENDS); if (Array.isArray(a) && a.length) return a; }
    catch { /* игнор — используем значения по умолчанию */ }
  }
  return [
    { id: 'level1', name: 'PHP (L1)',        url: 'http://localhost:8081', cost: 1 },
    { id: 'level2', name: 'Flask (L2)',      url: 'http://localhost:8082', cost: 1 },
    { id: 'level5', name: 'React+API (L5)',  url: 'http://localhost:8085', cost: 2 },
    { id: 'level6', name: 'Next.js (L6)',    url: 'http://localhost:8086', cost: 3 },
  ];
}

module.exports = { backends: load() };
