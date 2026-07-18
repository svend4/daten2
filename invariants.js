// invariants.js — инварианты расчётного слоя (проверяются в любой момент).
const { round } = require('./book');

function check(book, engine, expectedTotal) {
  const accts = book.accounts();
  const total = book.totalMoney();
  const noOverdraft = accts.every((a) => a.balance >= -1e-9 && round(a.balance - a.held) >= -1e-9);
  const activeHolds = book.activeHolds().length;
  const totalHeld = book.totalHeld();
  // «висящие» резервы: удержания есть, но им не соответствует ни один held-hold
  const heldConsistent = round(totalHeld) === round(book.activeHolds().reduce((s, h) => s + h.amount, 0));
  const conserved = expectedTotal == null ? true : Math.abs(total - expectedTotal) < 1e-6;
  return {
    ok: noOverdraft && heldConsistent && conserved,
    total, conserved, noOverdraft, activeHolds, totalHeld, heldConsistent,
    states: engine ? engine.byState() : {},
  };
}

module.exports = { check };
