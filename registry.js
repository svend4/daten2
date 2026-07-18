// registry.js — уровни-кандидаты с экономико-экологическим профилем.
// cost — €/запрос; watts — потребление под нагрузкой; grid — углеродоёмкость
// электросети площадки (gCO2/кВт·ч). Настраивается через ROUTER_BACKENDS (JSON).
function load() {
  if (process.env.ROUTER_BACKENDS) {
    try { const a = JSON.parse(process.env.ROUTER_BACKENDS); if (Array.isArray(a) && a.length) return a; }
    catch { /* значения по умолчанию */ }
  }
  return [
    { id: 'level1', name: 'PHP (L1)',       url: 'http://localhost:8081', cost: 0.0008, watts: 12, grid: 300 },
    { id: 'level2', name: 'Flask (L2)',     url: 'http://localhost:8082', cost: 0.0010, watts: 18, grid: 120 },
    { id: 'level4', name: 'Express (L4)',   url: 'http://localhost:8084', cost: 0.0012, watts: 16, grid: 250 },
    { id: 'level5', name: 'React+API (L5)', url: 'http://localhost:8085', cost: 0.0020, watts: 22, grid: 60 },
    { id: 'level6', name: 'Next.js (L6)',   url: 'http://localhost:8086', cost: 0.0035, watts: 30, grid: 40 },
  ];
}
module.exports = { backends: load() };
