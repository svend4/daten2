// store.js — журнал последних переговоров (для дашборда и интерпретации).
const MAX = 100;
let log = [];
function record(entry) { log.unshift(entry); if (log.length > MAX) log.pop(); return entry; }
const recent = (n = 30) => log.slice(0, n);
function stats() {
  const deals = log.filter((e) => e.deal);
  const avgDisc = deals.length ? deals.reduce((s, e) => s + e.deal.discount_pct, 0) / deals.length : 0;
  return { total: log.length, deals: deals.length, no_deals: log.length - deals.length, avg_discount_pct: Math.round(avgDisc * 100) / 100 };
}
module.exports = { record, recent, stats };
