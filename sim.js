// sim.js — цифровой двойник магазина: детерминированная симуляция на горизонт.
// Спрос эластичен по цене; товар портится каждый шаг (цветы!). Действие применяется
// в шаге 0, затем состояние катится вперёд. Это модель-предиктор для губернатора.
const clone = (s) => ({ cash: s.cash, products: s.products.map((p) => ({ ...p })) });

function defaultState() {
  return {
    cash: 5000,
    products: [
      { id: 'rose', name: 'Роза', price: 200, refPrice: 200, stock: 5, cost: 80, baseDemand: 8, elasticity: 1.5, spoil: 0.1 },
      { id: 'tulip', name: 'Тюльпан', price: 90, refPrice: 90, stock: 100, cost: 40, baseDemand: 12, elasticity: 2.0, spoil: 0.1 },
    ],
  };
}

function applyAction(state, action) {
  let reorderQty = 0, reorderSpend = 0;
  if (!action || action.type === 'noop') return { reorderQty, reorderSpend };
  const p = state.products.find((x) => x.id === action.productId);
  if (!p) return { reorderQty, reorderSpend };
  if (action.type === 'reorder') { const q = Math.max(0, Math.round(action.quantity || 0)); p.stock += q; state.cash -= q * p.cost; reorderQty = q; reorderSpend = q * p.cost; }
  else if (action.type === 'reprice') { p.price = Math.max(1, Number(action.newPrice) || p.price); }
  return { reorderQty, reorderSpend };
}

function rollForward(state0, action, { steps = 10 } = {}) {
  const state = clone(state0);
  const baseStock = state.products.reduce((s, p) => s + p.stock, 0);
  const { reorderQty, reorderSpend } = applyAction(state, action);
  let revenue = 0, unitsSold = 0, cogs = 0, spoilageUnits = 0, spoilageCost = 0, stockoutSteps = 0;
  let minCash = state.cash;
  const nP = state.products.length;
  for (let t = 0; t < steps; t++) {
    let stepRevenue = 0;
    for (const p of state.products) {
      const d = Math.max(0, Math.round(p.baseDemand * Math.pow(p.refPrice / p.price, p.elasticity)));
      if (d > p.stock) stockoutSteps++;
      const sales = Math.min(d, p.stock);
      stepRevenue += sales * p.price; unitsSold += sales; cogs += sales * p.cost; p.stock -= sales;
      const spoil = Math.floor(p.stock * p.spoil);
      p.stock -= spoil; spoilageUnits += spoil; spoilageCost += spoil * p.cost;
    }
    state.cash += stepRevenue; revenue += stepRevenue; minCash = Math.min(minCash, state.cash);
  }
  const r2 = (x) => Math.round(x * 100) / 100;
  return {
    steps, products: nP, reorderQty, reorderSpend,
    revenue: r2(revenue), unitsSold, cogs: r2(cogs), spoilageUnits, spoilageCost: r2(spoilageCost),
    stockoutSteps, stockoutRate: Math.round((stockoutSteps / (steps * nP)) * 1000) / 1000,
    endStock: state.products.reduce((s, p) => s + p.stock, 0), minCash: r2(minCash), endCash: r2(state.cash),
    totalBaseStock: baseStock + reorderQty,
    spoilageRate: Math.round((spoilageUnits / Math.max(1, baseStock + reorderQty)) * 1000) / 1000,
    profit: r2(revenue - cogs - spoilageCost),
  };
}

module.exports = { defaultState, rollForward, applyAction, clone };
