// targets.js — пул уровней с управляемым состоянием сбоев (fault injection).
// Каждый уровень оборачивается инъектором хаоса: down / latencyMs / errorRate.
function load() {
  let list;
  if (process.env.CHAOS_TARGETS) { try { list = JSON.parse(process.env.CHAOS_TARGETS); } catch { /* default */ } }
  if (!Array.isArray(list) || !list.length) list = [
    { id: 'level1', name: 'PHP (L1)', url: 'http://localhost:8081' },
    { id: 'level2', name: 'Flask (L2)', url: 'http://localhost:8082' },
    { id: 'level4', name: 'Express (L4)', url: 'http://localhost:8084' },
  ];
  return list.map((t) => ({ ...t, fault: { down: false, latencyMs: 0, errorRate: 0 }, _c: 0 }));
}

const targets = load();
const byId = (id) => targets.find((t) => t.id === id);
function setFault(id, patch) {
  const t = id === 'all' ? null : byId(id);
  const apply = (x) => { if (patch.down != null) x.fault.down = !!patch.down; if (patch.latencyMs != null) x.fault.latencyMs = Math.max(0, Number(patch.latencyMs)); if (patch.errorRate != null) x.fault.errorRate = Math.max(0, Math.min(1, Number(patch.errorRate))); };
  if (id === 'all') targets.forEach(apply); else if (t) apply(t);
  return id === 'all' ? targets : t;
}
function clearFaults() { targets.forEach((t) => { t.fault = { down: false, latencyMs: 0, errorRate: 0 }; t._c = 0; }); }

module.exports = { targets, byId, setFault, clearFaults };
