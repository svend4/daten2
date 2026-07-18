// personas.js — сегменты синтетических покупателей.
// budget — максимально приемлемая цена за единицу; priceSensitivity — насколько
// цена гасит конверсию; conversionBase — базовая склонность к покупке;
// affinity — вес интереса по корню названия товара; featuredBonus — тяга к ★;
// maxQty — верх количества в заказе; weight — доля в потоке посетителей.
module.exports = [
  { id: 'romantic', name: 'Романтик',    weight: 3, budget: 5.0, priceSensitivity: 0.3, conversionBase: 0.60, featuredBonus: 0.3, maxQty: 5,  affinity: { 'роз': 1.0, 'пион': 0.6, 'тюльпан': 0.2 } },
  { id: 'budget',   name: 'Экономный',   weight: 3, budget: 1.2, priceSensitivity: 0.9, conversionBase: 0.50, featuredBonus: 0.0, maxQty: 3,  affinity: { 'тюльпан': 1.0, 'роз': 0.4, 'пион': 0.1 } },
  { id: 'event',    name: 'Организатор', weight: 1, budget: 3.0, priceSensitivity: 0.4, conversionBase: 0.70, featuredBonus: 0.2, maxQty: 20, affinity: { 'пион': 1.0, 'роз': 0.7, 'тюльпан': 0.6 } },
  { id: 'browser',  name: 'Зевака',      weight: 3, budget: 2.0, priceSensitivity: 0.6, conversionBase: 0.15, featuredBonus: 0.1, maxQty: 2,  affinity: { 'роз': 0.5, 'тюльпан': 0.5, 'пион': 0.5 } },
];
