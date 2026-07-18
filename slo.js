// slo.js — проверка гипотезы SLO по метрикам нагрузки.
function check(metrics, hypothesis = {}) {
  const violations = [];
  if (hypothesis.minSuccessRate != null && metrics.successRate < hypothesis.minSuccessRate)
    violations.push(`доступность ${Math.round(metrics.successRate * 100)}% < SLO ${Math.round(hypothesis.minSuccessRate * 100)}%`);
  if (hypothesis.maxP95Ms != null && metrics.p95 != null && metrics.p95 > hypothesis.maxP95Ms)
    violations.push(`p95 ${metrics.p95} мс > SLO ${hypothesis.maxP95Ms} мс`);
  return { ok: violations.length === 0, violations };
}
module.exports = { check };
