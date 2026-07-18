// experiments.js — декларативные chaos-эксперименты.
// faults применяются к пулу, затем прогоняется нагрузка через устойчивый фронт,
// и проверяется гипотеза SLO. expectSlo=false — эксперимент, где нарушение SLO
// ОЖИДАЕМО (доказывает, что харнесс ловит реальные отказы, а не всегда «зелёный»).
module.exports = [
  { id: 'steady-state', name: 'Стабильное состояние (без сбоев)', faults: [], hypothesis: { minSuccessRate: 0.99 }, expectSlo: true },
  { id: 'one-level-down', name: 'Один уровень упал → failover держит SLO', faults: [{ target: 0, down: true }], hypothesis: { minSuccessRate: 0.99 }, expectSlo: true },
  { id: 'one-level-slow', name: 'Один уровень тормозит', faults: [{ target: 0, latencyMs: 120 }], hypothesis: { minSuccessRate: 0.99 }, expectSlo: true },
  { id: 'level-errors', name: 'Уровень сыпет 500 → failover маскирует', faults: [{ target: 0, errorRate: 1.0 }], hypothesis: { minSuccessRate: 0.99 }, expectSlo: true },
  { id: 'all-down', name: 'Все уровни упали (нарушение SLO ожидаемо)', faults: [{ target: 'all', down: true }], hypothesis: { minSuccessRate: 0.99 }, expectSlo: false },
];
