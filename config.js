// config.js — конфигурация shadow/canary (мутируется через /api/config).
module.exports = {
  primary: (process.env.PRIMARY_URL || 'http://localhost:8081').replace(/\/$/, ''),   // текущая версия уровня
  candidate: (process.env.CANDIDATE_URL || '').replace(/\/$/, ''),                     // новая версия-кандидат
  mode: process.env.MODE || 'shadow',        // off | shadow | canary
  canaryPct: Number(process.env.CANARY_PCT || 0),  // доля живого трафика на кандидат (0..1)
  // поля, изменчивые по природе — не считать расхождением
  ignoreFields: (process.env.IGNORE_FIELDS || 'order_number,created_at,updated_at,changed_at,expires_at,token,timestamp,date').split(','),
  rollbackErrorRate: Number(process.env.ROLLBACK_RATE || 0.2),  // порог ошибок кандидата → откат
  minSamples: Number(process.env.MIN_SAMPLES || 5),
};
