// registry.js — реестр версий модели с жизненным циклом и указателем на продакшн.
// Промоушен и откат — атомарная смена указателя; история хранит прежние продакшн-
// версии для отката к «последней хорошей».
function createRegistry() {
  const versions = new Map();  // version → {version, artifact, canaryAgreement, state, ts}
  let prod = null;             // текущая продакшн-версия
  const prodHistory = [];      // стек прежних продакшн-версий (для отката)
  const incidents = [];

  function record(version, artifact, canaryAgreement, state) {
    versions.set(version, { version, artifact, canaryAgreement, state, ts: versions.size });
    return versions.get(version);
  }
  function promote(version) {
    if (prod && prod !== version) prodHistory.push(prod);
    if (versions.get(version)) versions.get(version).state = 'production';
    if (prod && versions.get(prod) && prod !== version) versions.get(prod).state = 'retired';
    prod = version;
  }
  function rollback(reason) {
    const prev = prodHistory.pop();
    if (!prev) return { ok: false, reason: 'нет предыдущей продакшн-версии' };
    if (versions.get(prod)) versions.get(prod).state = 'rolled-back';
    const from = prod; prod = prev;
    if (versions.get(prod)) versions.get(prod).state = 'production';
    incidents.push({ from, to: prod, reason });
    return { ok: true, from, to: prod, reason };
  }

  return {
    record, promote, rollback,
    production: () => prod,
    get: (v) => versions.get(v),
    all: () => [...versions.values()],
    incidents: () => incidents.slice(),
    stats: () => ({ versions: versions.size, production: prod, incidents: incidents.length }),
  };
}
module.exports = { createRegistry };
