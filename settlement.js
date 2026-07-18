// settlement.js — АТОМАРНЫЙ КЛИРИНГ сделок агент-агенту как SAGA. Плечи (legs)
// исполняются по порядку немедленным переводом (так средства промежуточного счёта,
// например эскроу, становятся доступны следующему плечу). Если любое плечо не
// проходит ИЛИ поставка не подтверждена — компенсация: уже исполненные плечи
// откатываются обратными переводами → эффект строго «всё или ничего».
// Идемпотентность по id: повтор возвращает тот же результат без повторного эффекта.
function createEngine(book) {
  const settlements = new Map();

  function compensate(committed) {
    for (let i = committed.length - 1; i >= 0; i--) { const l = committed[i]; book.transfer(l.to, l.from, l.amount); }
  }

  function settle(req) {
    if (settlements.has(req.id)) return settlements.get(req.id); // идемпотентность
    const legs = (req.legs || []).map((l) => ({ from: l.from, to: l.to, amount: Number(l.amount) }));
    const rec = { id: req.id, legs, state: 'pending', postings: [], reason: null, ts: req.ts };
    const committed = [];

    for (const leg of legs) {
      if (!book.get(leg.from) || !book.get(leg.to)) { rec.state = 'aborted'; rec.reason = 'нет счёта ' + (!book.get(leg.from) ? leg.from : leg.to); compensate(committed); rec.postings = []; settlements.set(req.id, rec); return rec; }
      if (book.available(leg.from) < leg.amount - 1e-9) { rec.state = 'aborted'; rec.reason = 'недостаточно средств: ' + leg.from; compensate(committed); rec.postings = []; settlements.set(req.id, rec); return rec; }
      book.transfer(leg.from, leg.to, leg.amount);
      committed.push(leg); rec.postings.push(leg);
    }
    if (req.deliver === false) { rec.state = 'aborted'; rec.reason = 'поставка не подтверждена'; compensate(committed); rec.postings = []; settlements.set(req.id, rec); return rec; }

    rec.state = 'settled';
    settlements.set(req.id, rec);
    return rec;
  }

  // реверс расчёта (спор/возврат): обратные переводы. Возможен, только если у
  // получателей ещё есть средства (иначе — отказ, без частичного эффекта).
  function reverse(settlementId, revId) {
    const s = settlements.get(settlementId);
    if (!s || s.state !== 'settled') return { error: 'нельзя реверсировать: нет расчёта или он не settled' };
    if (s.reversedBy) return settlements.get(s.reversedBy);
    const id = revId || 'rev-' + settlementId;
    const legs = s.legs.slice().reverse().map((l) => ({ from: l.to, to: l.from, amount: l.amount }));
    const rec = { id, reverses: settlementId, legs, state: 'pending', postings: [], reason: null };
    const committed = [];
    for (const leg of legs) {
      if (book.available(leg.from) < leg.amount - 1e-9) { rec.state = 'aborted'; rec.reason = 'получатель уже распорядился средствами: ' + leg.from; compensate(committed); rec.postings = []; settlements.set(id, rec); return rec; }
      book.transfer(leg.from, leg.to, leg.amount); committed.push(leg); rec.postings.push(leg);
    }
    rec.state = 'settled'; s.reversedBy = id; settlements.set(id, rec);
    return rec;
  }

  return {
    settle, reverse,
    get: (id) => settlements.get(id),
    all: () => [...settlements.values()],
    byState: () => { const m = {}; for (const s of settlements.values()) m[s.state] = (m[s.state] || 0) + 1; return m; },
  };
}

module.exports = { createEngine };
