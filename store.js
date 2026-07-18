// store.js — последний прогон бенчмарка в памяти (для метрик, дашборда, интерпретации).
let last = null; // { at, opts, results, ranked }

function set(run) { last = run; return last; }
const get = () => last;
function reset() { last = null; }

module.exports = { set, get, reset };
