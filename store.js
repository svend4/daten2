// store.js — состояние автономной петли: ряд снимков, журнал действий (ledger),
// очередь на одобрение, аудит, cooldown по товарам, kill-switch.
const policy = require('./policy');

let snapshots = [];
let ledger = [];   // исполненные/симулированные действия
let pending = [];  // ждут одобрения человека
let audit = [];    // все события
const cooldowns = {}; // productId -> номер цикла последнего действия
let paused = false;
let cycleNo = 0;

const MAXLOG = 500;
const cap = (a) => (a.length > MAXLOG ? a.slice(-MAXLOG) : a);

function recordSnapshot(products, t) {
  snapshots.push({ t, products: products.map((p) => ({ id: p.id, name: p.name, price: Number(p.price), stock: Number(p.stock), is_featured: !!p.is_featured })) });
  snapshots = cap(snapshots);
  return snapshots[snapshots.length - 1];
}
const allSnapshots = () => snapshots;

function audited(event) { audit.push({ ...event }); audit = cap(audit); return event; }
function addLedger(entry) { ledger.push(entry); ledger = cap(ledger); return entry; }
function addPending(action) { pending.push(action); return action; }
function takePending(id) { const i = pending.findIndex((a) => a.id === id); return i === -1 ? null : pending.splice(i, 1)[0]; }

function setCooldown(productId) { cooldowns[productId] = cycleNo; }
function onCooldown(productId) { return cooldowns[productId] !== undefined && (cycleNo - cooldowns[productId]) < policy.cooldownCycles; }

const pause = () => { paused = true; };
const resume = () => { paused = false; };
const isPaused = () => paused;
const nextCycle = () => (++cycleNo);
const currentCycle = () => cycleNo;

function state() {
  return {
    paused, cycle: cycleNo, snapshots: snapshots.length,
    pending: pending.length, executed: ledger.length,
    dryRun: policy.dryRun,
  };
}

module.exports = {
  recordSnapshot, allSnapshots, audited, addLedger, addPending, takePending,
  setCooldown, onCooldown, pause, resume, isPaused, nextCycle, currentCycle, state,
  get pendingList() { return pending; }, get ledgerList() { return ledger; }, get auditList() { return audit; },
  _reset() { snapshots = []; ledger = []; pending = []; audit = []; for (const k of Object.keys(cooldowns)) delete cooldowns[k]; paused = false; cycleNo = 0; },
};
