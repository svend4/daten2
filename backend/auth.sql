-- auth.sql — расширение уровня L5: пользователи и связь заказов с ними.
-- Каноническая schema.sql остаётся общей для всех уровней; auth-таблицы
-- существуют только здесь (авторизация — пила коммерции этого уровня).

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_orders (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, order_id)
);
