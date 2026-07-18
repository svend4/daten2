// agents.js — детерминированные стратегии агентов.
// Продавец уступает вниз к полу; покупатель поднимается к своему потолку.
// ZOPA (зона сделки) существует ⇔ бюджет покупателя ≥ пола продавца → торг сходится.
const policy = require('./policy');
const { round2 } = require('./protocol');

// Продавец: знает прайс P, держит пол; за опт даёт доп.скидку (двигает пол вниз).
function makeSeller(product, quantity) {
  const P = Number(product.price);
  const bulk = quantity >= policy.bulkThreshold ? policy.bulkBonus : 0;
  const floor = round2(P * (1 - policy.maxDiscount - bulk));
  return {
    role: 'seller', P, floor, ask: P,
    open() { this.ask = P; return this.ask; },
    // уступка вниз к полу в ответ на бид покупателя
    counter(bid) {
      const target = Math.max(this.floor, bid); // не ниже пола и не ниже бида
      this.ask = round2(Math.max(this.floor, this.ask - (this.ask - target) * policy.sellerConcession));
      return this.ask;
    },
  };
}

// Покупатель: потолок = min(бюджет за ед., прайс). Открывает низко, поднимается к потолку.
function makeBuyer(budgetPerUnit, product) {
  const P = Number(product.price);
  const cap = round2(Math.min(budgetPerUnit, P));
  return {
    role: 'buyer', cap, bid: round2(cap * 0.55),
    // поднимается к потолку в ответ на аск продавца
    counter(ask) {
      const target = Math.min(this.cap, ask); // не выше потолка и не выше аска
      this.bid = round2(Math.min(this.cap, this.bid + (target - this.bid) * policy.buyerConcession));
      return this.bid;
    },
  };
}

module.exports = { makeSeller, makeBuyer };
