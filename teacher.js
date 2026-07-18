// teacher.js — учитель-правила: размечает намерение реплики покупателя.
// Ученик учится ИМИТИРОВАТЬ учителя; согласие с ним — метрика качества модели.
// Подстроки (регулярки \w/\b не матчат кириллицу).
const CLASSES = ['catalog', 'price', 'order', 'greeting', 'other'];
const low = (s) => String(s || '').toLowerCase();
const has = (s, ...subs) => { const t = low(s); return subs.some((x) => t.includes(x)); };

function label(text) {
  if (has(text, 'привет', 'здравств', 'добрый день', 'добрый вечер', 'здравствуйте')) return 'greeting';
  if (has(text, 'цена', 'стоит', 'почём', 'почем', 'сколько сто')) return 'price';
  if (has(text, 'оформ', 'заказ', 'куп', 'беру', 'корзин', 'хочу заказать')) return 'order';
  if (has(text, 'каталог', 'ассортимент', 'что есть', 'покажи', 'роз', 'тюльпан', 'пион', 'букет')) return 'catalog';
  return 'other';
}
module.exports = { label, CLASSES };
