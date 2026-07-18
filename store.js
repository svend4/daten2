// store.js — последний прогон двойника в памяти (для дашборда и интерпретации).
let last = null;
const set = (run) => { last = run; return last; };
const get = () => last;
module.exports = { set, get };
