// pipeline.js — конвейер выката модели. deploy: артефакт → канареечная оценка на
// eval-выборке → ГЕЙТ (согласие ≥ floor И не хуже действующего) → промоушен или
// отказ. monitor: живое согласие продакшн-модели; ниже floor → АВТО-ОТКАТ к
// последней хорошей версии.
const model = require('./model');

const FLOOR = Number(process.env.SLO_FLOOR || 0.8);      // минимальное согласие с учителем
const REGRESSION_EPS = 0.02;                              // допустимая просадка против действующего

function deploy(registry, version, artifact, evalSet) {
  const canaryAgreement = model.agreement(artifact, evalSet);
  const incumbent = registry.production();
  const incAgreement = incumbent ? registry.get(incumbent).canaryAgreement : -Infinity;

  if (canaryAgreement < FLOOR) { registry.record(version, artifact, canaryAgreement, 'rejected'); return { version, promoted: false, reason: `согласие ${canaryAgreement} < SLO ${FLOOR}`, canaryAgreement, state: 'rejected' }; }
  if (incumbent && canaryAgreement < incAgreement - REGRESSION_EPS) { registry.record(version, artifact, canaryAgreement, 'rejected'); return { version, promoted: false, reason: `регрессия против ${incumbent} (${canaryAgreement} < ${incAgreement})`, canaryAgreement, state: 'rejected' }; }

  registry.record(version, artifact, canaryAgreement, 'canary');
  registry.promote(version);
  return { version, promoted: true, reason: incumbent ? `превзошёл/на уровне ${incumbent}` : 'первичный продакшн', canaryAgreement, state: 'production' };
}

// живой мониторинг: согласие продакшн-модели на свежих данных; ниже floor → откат
function monitor(registry, liveSamples) {
  const prod = registry.production();
  if (!prod) return { ok: false, reason: 'нет продакшн-модели' };
  const liveAgreement = model.agreement(registry.get(prod).artifact, liveSamples);
  if (liveAgreement < FLOOR) {
    const rb = registry.rollback(`живое согласие ${liveAgreement} < SLO ${FLOOR}`);
    return { prod, liveAgreement, breached: true, rolledBack: rb.ok, rollback: rb };
  }
  return { prod, liveAgreement, breached: false, rolledBack: false };
}

module.exports = { deploy, monitor, FLOOR };
