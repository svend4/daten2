-- Каноническая схема магазина цветов (очень богатая, два яруса).
-- Источник правды для всех уровней. Из неё генерируется flowers.db (init_db.py).
-- Имена канонические: quantity (не qty), image (не photo_path), отдельная таблица customers.

PRAGMA foreign_keys = ON;

-- =====================================================================
-- ЯРУС 1 — ПОСТОЯННЫЙ (durable): источник правды, хранится в SQL
-- =====================================================================

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    price       REAL NOT NULL CHECK (price >= 0),
    currency    TEXT NOT NULL DEFAULT 'EUR',
    image       TEXT NOT NULL DEFAULT '',
    sku         TEXT,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    is_active   INTEGER NOT NULL DEFAULT 1,
    is_featured INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_products_active   ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL,
    email       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    city        TEXT NOT NULL DEFAULT '',
    postal_code TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number     TEXT NOT NULL UNIQUE,          -- непубличный токен (защита от IDOR)
    customer_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    subtotal         REAL NOT NULL DEFAULT 0,
    discount         REAL NOT NULL DEFAULT 0,
    delivery_fee     REAL NOT NULL DEFAULT 0,
    total_amount     REAL NOT NULL DEFAULT 0,
    currency         TEXT NOT NULL DEFAULT 'EUR',
    status           TEXT NOT NULL DEFAULT 'new',      -- new|confirmed|preparing|delivering|completed|cancelled
    payment_status   TEXT NOT NULL DEFAULT 'pending',  -- pending|paid|refunded|failed
    delivery_address TEXT NOT NULL DEFAULT '',
    delivery_date    TEXT,
    notes            TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status);

CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id   INTEGER REFERENCES products(id) ON DELETE SET NULL,
    product_name TEXT NOT NULL,                       -- снимок названия на момент заказа
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   REAL NOT NULL,
    line_total   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);

CREATE TABLE IF NOT EXISTS order_status_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status     TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- =====================================================================
-- ЯРУС 2 — ВРЕМЕННЫЙ / КЭШ (temporal): можно вытеснять по TTL.
-- Уровень выбирает: держать корзину здесь ИЛИ в родном хранилище
-- (Flask session / Zustand localStorage / Redis на L7).
-- =====================================================================

CREATE TABLE IF NOT EXISTS carts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT                                    -- TTL: после этого можно вытеснять
);

CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id    INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity   INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    added_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS product_view_stats (
    product_id   INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    views        INTEGER NOT NULL DEFAULT 0,
    window_start TEXT NOT NULL DEFAULT (datetime('now'))  -- кэш-окно, вытесняемое
);
