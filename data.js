// data.js — детерминированный генератор размеченных реплик (mulberry32).
// Каждая реплика собирается из банка по классу и размечается учителем.
const teacher = require('./teacher');

function mulberry32(seed) { let t = seed >>> 0; return () => { t += 0x6d2b79f5; let x = Math.imul(t ^ (t >>> 15), 1 | t); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }

const BANKS = {
  greeting: ['привет', 'здравствуйте', 'добрый день', 'добрый вечер', 'привет, есть кто', 'здравствуй'],
  price: ['сколько стоит роза', 'цена букета', 'почём тюльпаны', 'сколько стоит пион', 'цена доставки', 'почем розы'],
  order: ['хочу оформить заказ', 'оформи заказ', 'беру три розы', 'добавь в корзину', 'куплю букет', 'хочу заказать пионы'],
  catalog: ['покажи каталог', 'что у вас есть', 'ассортимент', 'какие букеты есть', 'покажи розы', 'есть тюльпаны'],
  other: ['какая погода', 'расскажи анекдот', 'как дела', 'спасибо', 'до свидания', 'что нового'],
};
const SUFFIX = ['', '!', ', пожалуйста', '?', ' сегодня'];

function generate(n, seed, { classes } = {}) {
  const rnd = mulberry32(seed);
  const cls = classes || teacher.CLASSES;
  const out = [];
  for (let i = 0; i < n; i++) {
    const c = cls[Math.floor(rnd() * cls.length)];
    const bank = BANKS[c];
    const base = bank[Math.floor(rnd() * bank.length)];
    const text = base + SUFFIX[Math.floor(rnd() * SUFFIX.length)];
    out.push({ text, label: teacher.label(text) });
  }
  return out;
}
module.exports = { generate, BANKS };
