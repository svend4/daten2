// init_db.js — генерирует flowers.db из канонических schema.sql + seed.sql.
// Идемпотентно: schema — CREATE IF NOT EXISTS, seed — INSERT OR IGNORE.
const fs = require('fs');
const path = require('path');
const sqlite3 = require('sqlite3').verbose();

const DB_PATH = process.env.DATABASE_PATH || path.join(__dirname, 'flowers.db');

function initDb() {
    return new Promise((resolve, reject) => {
        const db = new sqlite3.Database(DB_PATH);
        const schema = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');
        const seed = fs.readFileSync(path.join(__dirname, 'seed.sql'), 'utf8');
        db.exec(schema, (err) => {
            if (err) return reject(err);
            db.exec(seed, (err2) => {
                if (err2) return reject(err2);
                db.close((err3) => (err3 ? reject(err3) : resolve(DB_PATH)));
            });
        });
    });
}

module.exports = { initDb, DB_PATH };

if (require.main === module) {
    initDb()
        .then((p) => console.log(`БД готова: ${p}`))
        .catch((e) => { console.error(e); process.exit(1); });
}
