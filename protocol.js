// protocol.js — протокол agent-to-agent сообщений (общий язык для любых агентов).
// Сообщение: { round, from, type, price, note }. Типы: greet | ask | bid | accept | reject.
const TYPES = ['greet', 'ask', 'bid', 'accept', 'reject'];
const round2 = (n) => Math.round(n * 100) / 100;

function msg(from, type, price, note, round) {
  if (!TYPES.includes(type)) throw new Error('неизвестный тип сообщения: ' + type);
  return { round, from, type, price: price == null ? null : round2(price), note: note || '' };
}
const isClose = (m) => m.type === 'accept' || m.type === 'reject';

module.exports = { TYPES, msg, isClose, round2 };
