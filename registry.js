// registry.js — семь стеков-кандидатов для бенчмарка (или деплои уровней).
// Все реализуют единый контракт, поэтому сравнимы «в лоб». Настраивается через
// OBS_LEVELS (JSON) — иначе локальные значения по умолчанию.
function load() {
  if (process.env.OBS_LEVELS) {
    try { const a = JSON.parse(process.env.OBS_LEVELS); if (Array.isArray(a) && a.length) return a; }
    catch { /* игнор — значения по умолчанию */ }
  }
  return [
    { id: 'level1', name: 'PHP',           url: 'http://localhost:8081' },
    { id: 'level2', name: 'Flask',         url: 'http://localhost:8082' },
    { id: 'level3', name: 'Django',        url: 'http://localhost:8083' },
    { id: 'level4', name: 'Express',       url: 'http://localhost:8084' },
    { id: 'level5', name: 'React+Flask',   url: 'http://localhost:8085' },
    { id: 'level6', name: 'Next.js',       url: 'http://localhost:8086' },
    { id: 'level7', name: 'Microservices', url: 'http://localhost:8087' },
  ];
}

module.exports = { levels: load(), ROUTER_URL: (process.env.ROUTER_URL || '').replace(/\/$/, '') };
