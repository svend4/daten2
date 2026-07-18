// book.js — ДВОЙНАЯ ЗАПИСЬ с сохранением денег. Каждый перевод балансирован
// (сколько списали — столько зачислили), поэтому суммарная масса денег по всем
// счетам инвариантна. Эскроу выражен через holds: reserve резервирует доступные
// средства (available = balance − held), capture превращает резерв в перевод,
// release снимает резерв. Овердрафт запрещён: нельзя зарезервировать/перевести
// больше доступного.
const round = (x) => Math.round(x * 100) / 100;
const EPS = 1e-9;

function createBook() {
  const accounts = new Map();       // id → {id, balance, held}
  const holds = new Map();          // holdId → {account, amount, state}
  let holdSeq = 0;

  function open(id, initial = 0) {
    if (accounts.has(id)) return accounts.get(id);
    const a = { id, balance: round(Number(initial) || 0), held: 0 };
    accounts.set(id, a);
    return a;
  }
  const get = (id) => accounts.get(id);
  const available = (id) => { const a = accounts.get(id); return a ? round(a.balance - a.held) : 0; };

  // перевод (двойная запись): списать с from, зачислить to. Масса сохраняется.
  function transfer(from, to, amount) {
    const f = accounts.get(from), t = accounts.get(to);
    if (!f || !t) throw new Error('нет счёта');
    if (round(f.balance - f.held) < amount - EPS) throw new Error('овердрафт ' + from);
    f.balance = round(f.balance - amount);
    t.balance = round(t.balance + amount);
    return true;
  }

  // эскроу: резерв доступных средств
  function reserve(account, amount) {
    const a = accounts.get(account);
    if (!a) throw new Error('нет счёта ' + account);
    if (round(a.balance - a.held) < amount - EPS) return null;
    a.held = round(a.held + amount);
    const id = 'h' + (++holdSeq);
    holds.set(id, { id, account, amount, state: 'held' });
    return id;
  }
  function release(holdId) {
    const h = holds.get(holdId);
    if (!h || h.state !== 'held') return false;
    const a = accounts.get(h.account); a.held = round(a.held - h.amount);
    h.state = 'released';
    return true;
  }
  // capture: превратить резерв в перевод получателю
  function capture(holdId, to) {
    const h = holds.get(holdId);
    if (!h || h.state !== 'held') return false;
    const a = accounts.get(h.account), t = accounts.get(to);
    if (!t) throw new Error('нет счёта ' + to);
    a.held = round(a.held - h.amount);
    a.balance = round(a.balance - h.amount);
    t.balance = round(t.balance + h.amount);
    h.state = 'captured';
    return true;
  }

  const totalMoney = () => round([...accounts.values()].reduce((s, a) => s + a.balance, 0));
  const totalHeld = () => round([...accounts.values()].reduce((s, a) => s + a.held, 0));
  const snapshot = () => [...accounts.values()].map((a) => ({ id: a.id, balance: a.balance, held: a.held, available: round(a.balance - a.held) }));
  const activeHolds = () => [...holds.values()].filter((h) => h.state === 'held');

  return { open, get, available, transfer, reserve, release, capture, totalMoney, totalHeld, snapshot, activeHolds, accounts: () => [...accounts.values()] };
}

module.exports = { createBook, round };
