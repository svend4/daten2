// stats.js — накопление результатов shadow-сравнений и canary-метрик.
let shadow = { compared: 0, matches: 0, diffs: 0, candidateErrors: 0, samples: [] };
let canary = { primary: { served: 0, errors: 0 }, candidate: { served: 0, errors: 0 }, rollbacks: 0, events: [] };

function recordShadow(kind, detail) {
  shadow.compared++;
  if (kind === 'match') shadow.matches++;
  else if (kind === 'diff') { shadow.diffs++; if (detail) shadow.samples.unshift(detail); shadow.samples = shadow.samples.slice(0, 10); }
  else if (kind === 'candidate-error') shadow.candidateErrors++;
}

function recordCanary(side, ok) {
  const s = canary[side]; s.served++; if (!ok) s.errors++;
}
function event(msg) { canary.events.unshift({ msg }); canary.events = canary.events.slice(0, 20); }
function rollback(msg) { canary.rollbacks++; event('ROLLBACK: ' + msg); }

function shadowReport() {
  const rate = shadow.compared ? shadow.matches / shadow.compared : null;
  return { ...shadow, matchRate: rate == null ? null : Math.round(rate * 1000) / 1000 };
}
function canaryReport() {
  const er = (s) => (s.served ? Math.round((s.errors / s.served) * 1000) / 1000 : 0);
  return { primary: { ...canary.primary, errorRate: er(canary.primary) }, candidate: { ...canary.candidate, errorRate: er(canary.candidate) }, rollbacks: canary.rollbacks, events: canary.events };
}
function reset() {
  shadow = { compared: 0, matches: 0, diffs: 0, candidateErrors: 0, samples: [] };
  canary = { primary: { served: 0, errors: 0 }, candidate: { served: 0, errors: 0 }, rollbacks: 0, events: [] };
}

module.exports = { recordShadow, recordCanary, event, rollback, shadowReport, canaryReport, reset, _canary: () => canary };
