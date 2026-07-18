// registry.js — реестр сервисов стенда для портала. Каждый сервис отдаёт /api/health.
// url — внутренний адрес (в compose по имени сервиса), dash — куда ведёт ссылка в UI.
// Переопределяется через PORTAL_SERVICES (JSON).
function load() {
  if (process.env.PORTAL_SERVICES) {
    try { const a = JSON.parse(process.env.PORTAL_SERVICES); if (Array.isArray(a) && a.length) return a; }
    catch { /* значения по умолчанию */ }
  }
  const dash = (p) => `http://localhost:${p}`;
  return [
    // Маршрутизация
    { id: 'router', name: 'ML-роутер', cat: 'Маршрутизация', url: 'http://router:8073', dash: dash(8080) },
    { id: 'green-router', name: 'Green/FinOps-роутер', cat: 'Маршрутизация', url: 'http://green-router:8091', dash: dash(8093) },
    { id: 'shadow-canary', name: 'Shadow/Canary', cat: 'Маршрутизация', url: 'http://shadow-canary:8094', dash: dash(8094) },
    // Живые уровни
    { id: 'level1', name: 'L1 · PHP', cat: 'Уровни', url: 'http://level1:80', dash: dash(8081) },
    { id: 'level2', name: 'L2 · Flask', cat: 'Уровни', url: 'http://level2:10000', dash: dash(8082) },
    { id: 'level3', name: 'L3 · Django', cat: 'Уровни', url: 'http://level3:10000', dash: dash(8083) },
    { id: 'level4', name: 'L4 · Express', cat: 'Уровни', url: 'http://level4:10000', dash: dash(8084) },
    { id: 'level5', name: 'L5 · React+API', cat: 'Уровни', url: 'http://level5:10000', dash: dash(8085) },
    // ИИ · коммерция
    { id: 'storefront', name: 'Разговорная витрина', cat: 'ИИ · коммерция', url: 'http://storefront:8070', dash: dash(8070) },
    { id: 'search', name: 'Семантический поиск', cat: 'ИИ · коммерция', url: 'http://search:8072', dash: dash(8072) },
    { id: 'rag', name: 'RAG + память', cat: 'ИИ · коммерция', url: 'http://rag:8079', dash: dash(8079) },
    { id: 'vision', name: 'Vision', cat: 'ИИ · коммерция', url: 'http://vision:8088', dash: dash(8088) },
    { id: 'market', name: 'Рынок агентов', cat: 'ИИ · коммерция', url: 'http://market:8078', dash: dash(8078) },
    // ИИ · операции
    { id: 'manager', name: 'ИИ-управляющий', cat: 'ИИ · операции', url: 'http://manager:8071', dash: dash(8071) },
    { id: 'autonomous', name: 'Автономный управляющий', cat: 'ИИ · операции', url: 'http://autonomous:8077', dash: dash(8077) },
    { id: 'twin', name: 'Цифровой двойник', cat: 'ИИ · операции', url: 'http://twin:8075', dash: dash(8075) },
    { id: 'firewall', name: 'Файрвол ИИ-агента', cat: 'ИИ · операции', url: 'http://firewall:8076', dash: dash(8076) },
    { id: 'distillation', name: 'Дистилляция', cat: 'ИИ · операции', url: 'http://distillation:8089', dash: dash(8089) },
    // Качество и наблюдаемость
    { id: 'observability', name: 'Наблюдаемость', cat: 'Качество', url: 'http://observability:8074', dash: dash(8074) },
    { id: 'evals', name: 'Авто-эвалы', cat: 'Качество', url: 'http://evals:8090', dash: dash(8090) },
    { id: 'contract-cdc', name: 'Контракт CDC', cat: 'Качество', url: 'http://contract-cdc:8095', dash: dash(8095) },
    { id: 'chaos-harness', name: 'Chaos-харнесс', cat: 'Качество', url: 'http://chaos-harness:8096', dash: dash(8096) },
    { id: 'property-tests', name: 'Property-тесты', cat: 'Качество', url: 'http://property-tests:8098', dash: dash(8098) },
    { id: 'event-bus', name: 'Событийная шина', cat: 'Качество', url: 'http://event-bus:8097', dash: dash(8097) },
  ];
}
module.exports = { services: load() };
