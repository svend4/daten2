# init_db.py — генерирует flowers.db из канонических schema.sql + seed.sql.
# Идемпотентно: schema использует CREATE IF NOT EXISTS, seed — INSERT OR IGNORE.
import os
import sqlite3

DB_PATH = os.environ.get('DATABASE_PATH', 'flowers.db')
HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    with open(os.path.join(HERE, name), encoding='utf-8') as f:
        return f.read()


def init_db(force=False):
    conn = sqlite3.connect(DB_PATH)
    if force:
        conn.executescript(
            'DELETE FROM order_items; DELETE FROM orders; DELETE FROM customers;'
            'DELETE FROM products; DELETE FROM categories;'
        )
    conn.executescript(_read('schema.sql'))
    conn.executescript(_read('seed.sql'))
    conn.commit()
    conn.close()


if __name__ == '__main__':
    import sys
    init_db(force='--force' in sys.argv)
    print(f'БД готова: {DB_PATH}')
