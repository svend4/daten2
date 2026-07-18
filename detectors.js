// detectors.js — детерминированные детекторы (RU+EN).
// Три поверхности: (1) ввод покупателя (prompt-injection), (2) предлагаемый вызов
// инструмента (злоупотребление аргументами), (3) вывод агента (утечки).
const policy = require('./policy');

// Паттерны инъекций во ввод: { re, cat, weight }
const INPUT_PATTERNS = [
  // подмена/сброс инструкций
  { re: /ignore\s+(all\s+|the\s+|any\s+)?(previous|prior|above)\s+(instructions?|prompts?)/i, cat: 'instruction-override', w: 60 },
  { re: /disregard\s+(all\s+|the\s+)?(previous|prior|above|earlier)?\s*(instructions?|rules?)/i, cat: 'instruction-override', w: 60 },
  { re: /забудь\s+(все\s+|всё\s+)?(предыдущи[\wа-яё]+|прошл[\wа-яё]+|прежни[\wа-яё]+|ране[\wа-яё]+)?\s*(инструкци[\wа-яё]+|указани[\wа-яё]+|правила)/i, cat: 'instruction-override', w: 60 },
  { re: /(нов[\wа-яё]+\s+инструкци[\wа-яё]+|new\s+instructions?)\s*[:.-]/i, cat: 'instruction-override', w: 50 },
  { re: /(не\s+обращай\s+внимани[\wа-яё]+|проигнорируй)\s+.{0,20}(инструкци[\wа-яё]+|указани[\wа-яё]+|правил[\wа-яё]+)/i, cat: 'instruction-override', w: 55 },
  // ролевые/джейлбрейк
  { re: /you\s+are\s+now\s+/i, cat: 'role-hijack', w: 45 },
  { re: /ты\s+(теперь|отныне)\s+/i, cat: 'role-hijack', w: 40 },
  { re: /act\s+as\s+(an?\s+)?(admin|administrator|developer|root|system)/i, cat: 'role-hijack', w: 50 },
  { re: /(developer\s+mode|режим\s+разработчик[\wа-яё]+|jailbreak|dan\s+mode)/i, cat: 'role-hijack', w: 55 },
  // эксфильтрация / утечка
  { re: /(reveal|show|print|repeat)\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions?)/i, cat: 'exfiltration', w: 55 },
  { re: /(покажи|выведи|повтори|расскажи)\s+.{0,25}(систем[\wа-яё]+\s+)?(промпт|инструкци[\wа-яё]+)/i, cat: 'exfiltration', w: 55 },
  { re: /(api[_\s-]?key|access\s+token|секретн[\wа-яё]+\s+ключ|пароль|password|токен\s+доступа)/i, cat: 'exfiltration', w: 45 },
  { re: /(все\s+заказы|чужи[\wа-яё]+\s+заказ[\wа-яё]+|list\s+all\s+orders|other\s+customers?)/i, cat: 'exfiltration', w: 45 },
  // манипуляция ценой/скидкой
  { re: /(скидк[\wа-яё]+|discount)\D{0,12}(100|99|бесплатн[\wа-яё]+|free|zero|ноль)/i, cat: 'price-manipulation', w: 50 },
  { re: /(цен[\wа-яё]+|price)\D{0,10}(=\s*)?(0|ноль|zero|бесплатн[\wа-яё]+|free)\b/i, cat: 'price-manipulation', w: 50 },
  { re: /(set|change|измени|поставь)\s+(the\s+)?(price|цен[\wа-яё]+|скидк[\wа-яё]+|discount)/i, cat: 'price-manipulation', w: 50 },
  // экранирование границ данных / разметка
  { re: /(<\/?(system|assistant|user|inst)>|\[\/?INST\]|<\|[^|]*\|>|```\s*system)/i, cat: 'boundary-escape', w: 35 },
  // массовые объёмы
  { re: /\b(\d{3,}|тысяч[\wа-яё]*|миллион[\wа-яё]*|million|thousand)\s*(роз|тюльпан[\wа-яё]*|пион[\wа-яё]*|букет[\wа-яё]*|штук|шт|units?|items?)/i, cat: 'bulk-abuse', w: 35 },
];

function scanInput(text) {
  const t = String(text || '');
  const matched = [];
  const cats = new Set();
  let risk = 0;
  for (const p of INPUT_PATTERNS) {
    const m = t.match(p.re);
    if (m) { matched.push({ category: p.cat, match: m[0].slice(0, 60) }); cats.add(p.cat); risk += p.w; }
  }
  return { risk: Math.min(100, risk), categories: [...cats], matches: matched };
}

// Санитизация: вырезать сработавшие инъекции, оставив полезный смысл.
function sanitize(text) {
  let out = String(text || '');
  for (const p of INPUT_PATTERNS) out = out.replace(p.re, '[удалено правилом безопасности]');
  return out;
}

// Утечки в выводе агента.
const OUTPUT_PATTERNS = [
  { re: /sk-ant-[a-z0-9-]+/i, cat: 'secret-leak', w: 80 },
  { re: /(api[_\s-]?key|secret\s+key)\s*[:=]/i, cat: 'secret-leak', w: 60 },
  { re: /(system\s+prompt|систем[\wа-яё]+\s+промпт)\s*[:\-]/i, cat: 'prompt-leak', w: 60 },
  { re: /you\s+are\s+a\s+.{0,40}\s+assistant/i, cat: 'prompt-leak', w: 40 },
  { re: /(ORD-[A-Za-z0-9-]+[,;\s]+){4,}/, cat: 'bulk-order-leak', w: 50 }, // много чужих номеров
];
function scanOutput(text) {
  const t = String(text || '');
  const matched = [];
  const cats = new Set();
  let risk = 0;
  for (const p of OUTPUT_PATTERNS) {
    const m = t.match(p.re);
    if (m) { matched.push({ category: p.cat, match: m[0].slice(0, 40) }); cats.add(p.cat); risk += p.w; }
  }
  return { risk: Math.min(100, risk), categories: [...cats], matches: matched };
}

// Проверка предлагаемого вызова инструмента.
function validateTool(tool, input) {
  const violations = [];
  let risk = 0;
  const clamped = JSON.parse(JSON.stringify(input || {}));

  if (!policy.tools.allowed.includes(tool)) {
    return { violations: [{ code: 'tool-not-allowed', detail: `инструмент «${tool}» не разрешён` }], risk: 80, clamped, blocked: true };
  }
  if (tool !== 'create_order') return { violations, risk, clamped, blocked: false };

  const cfg = policy.tools.create_order;

  // запрещённые клиентские поля (попытка задать цену/скидку/тотал)
  for (const k of cfg.forbiddenKeys) {
    if (clamped[k] !== undefined) { violations.push({ code: 'forbidden-field', detail: `поле «${k}» задаёт клиент` }); risk += 60; delete clamped[k]; }
  }

  // имя
  const nameScan = scanInput(clamped.name || '');
  if (nameScan.risk > 0) { violations.push({ code: 'injection-in-name', detail: 'инъекция в имени' }); risk += nameScan.risk; }
  if ((clamped.name || '').length > cfg.maxNameLen) { violations.push({ code: 'name-too-long', detail: 'слишком длинное имя' }); risk += 20; clamped.name = String(clamped.name).slice(0, cfg.maxNameLen); }

  // позиции
  const items = Array.isArray(clamped.items) ? clamped.items : [];
  if (!items.length) { violations.push({ code: 'no-items', detail: 'нет позиций' }); risk += 40; }
  if (items.length > cfg.maxItems) { violations.push({ code: 'too-many-items', detail: `позиций > ${cfg.maxItems}` }); risk += 40; clamped.items = items.slice(0, cfg.maxItems); }

  let units = 0;
  for (const it of clamped.items || []) {
    const q = Number(it.quantity);
    if (!Number.isInteger(q) || q <= 0) { violations.push({ code: 'bad-quantity', detail: `недопустимое количество: ${it.quantity}` }); risk += 50; it.quantity = 1; }
    else if (q > cfg.maxQtyPerItem) { violations.push({ code: 'quantity-clamped', detail: `${q} → ${cfg.maxQtyPerItem}` }); risk += 30; it.quantity = cfg.maxQtyPerItem; }
    units += Number(it.quantity);
    if (!Number.isInteger(Number(it.product_id)) || Number(it.product_id) <= 0) { violations.push({ code: 'bad-product-id', detail: `product_id: ${it.product_id}` }); risk += 40; }
  }
  if (units > cfg.maxUnits) { violations.push({ code: 'too-many-units', detail: `всего единиц ${units} > ${cfg.maxUnits}` }); risk += 40; }

  return { violations, risk: Math.min(100, risk), clamped, blocked: false };
}

module.exports = { scanInput, scanOutput, validateTool, sanitize, INPUT_PATTERNS };
