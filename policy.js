// policy.js — правила переговоров, задаёт управляющий-агент.
// Продавец никогда не опускается ниже пола (list × (1 − maxDiscount)).
module.exports = {
  maxDiscount: Number(process.env.MAX_DISCOUNT || 0.2),    // максимум уступки от прайса
  maxRounds: Number(process.env.MAX_ROUNDS || 8),          // предел раундов торга
  sellerConcession: Number(process.env.SELLER_STEP || 0.4), // скорость уступок продавца
  buyerConcession: Number(process.env.BUYER_STEP || 0.4),   // скорость уступок покупателя
  bulkBonus: Number(process.env.BULK_BONUS || 0.05),        // доп. скидка за крупный опт
  bulkThreshold: Number(process.env.BULK_THRESHOLD || 10),  // от какого кол-ва опт
};
