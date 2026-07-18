// store.js — журнал последних решений файрвола + счётчики (для дашборда и /api/ask).
const MAX = 200;
const log = [];
const counts = { allow: 0, sanitize: 0, 'allow-clamped': 0, redact: 0, block: 0 };
const byCategory = {};

function record(decision, meta = {}) {
  counts[decision.action] = (counts[decision.action] || 0) + 1;
  for (const c of decision.categories || []) byCategory[c] = (byCategory[c] || 0) + 1;
  for (const v of decision.violations || []) byCategory[v.code] = (byCategory[v.code] || 0) + 1;
  log.unshift({ surface: decision.surface, action: decision.action, risk: decision.risk, categories: decision.categories, violations: decision.violations, ...meta });
  if (log.length > MAX) log.pop();
  return decision;
}

const recent = (n = 50) => log.slice(0, n);
const stats = () => ({ counts: { ...counts }, byCategory: { ...byCategory }, total: log.length });

module.exports = { record, recent, stats };
