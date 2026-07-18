// mutate.js — генеративное расширение ввода: проверяем поведение НЕ на одном примере,
// а на семействе эквивалентных формулировок (перестановки регистра, вежливость,
// пунктуация). Детерминировано → воспроизводимо.
function variants(input) {
  const s = String(input).trim();
  const set = new Set([
    s,
    s + '!',
    s + ', пожалуйста',
    s.charAt(0).toUpperCase() + s.slice(1),
    s.toLowerCase(),
    'слушай, ' + s,
  ]);
  return [...set];
}
module.exports = { variants };
