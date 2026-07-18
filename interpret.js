// interpret.js — детерминированная сводка по расчётному слою.
const invariants = require('./invariants');

function ask(ctx, text) {
  const low = (text || '').toLowerCase();
  const { book, engine, initialTotal } = ctx;
  const inv = invariants.check(book, engine, initialTotal);

  if (/инвариант|сохран|овердрафт|резерв|hold|целостн|баланс сходит/.test(low)) {
    return { reply: `Инварианты: масса денег ${inv.total} (${inv.conserved ? 'сохранена' : 'НАРУШЕНА'}), овердрафтов нет: ${inv.noOverdraft ? 'да' : 'НЕТ'}, активных резервов ${inv.activeHolds} (${inv.totalHeld}). Итог: ${inv.ok ? 'все инварианты держатся ✓' : 'НАРУШЕНИЕ ⚠'}`, engine: 'rules' };
  }
  if (/расчёт|settle|сделк|состоян|клиринг/.test(low)) {
    const st = engine.byState();
    return { reply: `Расчётов: settled ${st.settled || 0}, aborted ${st.aborted || 0}. Все — атомарны (всё-или-ничего), с идемпотентностью по id и возможностью реверса.`, engine: 'rules' };
  }
  const s = book.snapshot();
  return { reply: `Счетов: ${s.length}. Масса денег: ${inv.total} (сохранена: ${inv.conserved ? 'да' : 'нет'}). Активных эскроу-резервов: ${inv.activeHolds}.`, engine: 'rules' };
}
module.exports = { ask };
