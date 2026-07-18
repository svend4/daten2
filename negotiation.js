// negotiation.js — раннер сессии торга между двумя агентами по протоколу A2A.
// Продавец открывает прайсом, стороны обмениваются встречными, сходятся к сделке
// или расходятся за maxRounds. Сделка никогда не ниже пола продавца.
const policy = require('./policy');
const { msg, round2 } = require('./protocol');

function dealOf(seller, price, rounds) {
  return {
    agreed_unit: round2(price),
    list: seller.P,
    floor: seller.floor,
    discount_pct: round2(((seller.P - price) / seller.P) * 100),
    rounds,
  };
}

function run(seller, buyer) {
  const transcript = [];
  const tol = Math.max(0.05, seller.P * 0.03); // сходимся, когда разрыв закрылся
  const settle = (bid, ask) => round2(Math.max(seller.floor, (bid + ask) / 2));
  let round = 0;
  transcript.push(msg('seller', 'greet', null, 'Здравствуйте! Обсудим цену.', round));
  let ask = seller.open();
  transcript.push(msg('seller', 'ask', ask, 'начальная цена', round));

  for (round = 1; round <= policy.maxRounds; round++) {
    const bid = buyer.counter(ask);
    transcript.push(msg('buyer', 'bid', bid, '', round));
    if (ask - bid <= tol) {
      const price = settle(bid, ask);
      transcript.push(msg('buyer', 'accept', price, 'по рукам', round));
      return { deal: dealOf(seller, price, round), transcript };
    }
    const newAsk = seller.counter(bid);
    transcript.push(msg('seller', 'ask', newAsk, 'встречное предложение', round));
    if (newAsk - bid <= tol) {
      const price = settle(bid, newAsk);
      transcript.push(msg('seller', 'accept', price, 'договорились', round));
      return { deal: dealOf(seller, price, round), transcript };
    }
    ask = newAsk;
  }
  transcript.push(msg('seller', 'reject', seller.floor, 'ниже пола не могу', policy.maxRounds));
  return { deal: null, transcript };
}

module.exports = { run };
