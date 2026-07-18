-- Каноническая схема (Postgres) — два яруса. Аналог schema.sql/seed.sql на L1–L5.

-- =====================================================================
-- ЯРУС 1 — ПОСТОЯННЫЙ (durable)
-- =====================================================================

CREATE TABLE IF NOT EXISTS categories (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  slug        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  slug        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  price       NUMERIC(10,2) NOT NULL CHECK (price >= 0),
  currency    TEXT NOT NULL DEFAULT 'EUR',
  sku         TEXT,
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  image       TEXT NOT NULL DEFAULT '',
  stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  is_featured BOOLEAN NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS customers (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  phone       TEXT NOT NULL,
  email       TEXT NOT NULL DEFAULT '',
  address     TEXT NOT NULL DEFAULT '',
  city        TEXT NOT NULL DEFAULT '',
  postal_code TEXT NOT NULL DEFAULT '',
  notes       TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
  id               SERIAL PRIMARY KEY,
  order_number     TEXT NOT NULL UNIQUE,
  customer_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  subtotal         NUMERIC(10,2) NOT NULL DEFAULT 0,
  discount         NUMERIC(10,2) NOT NULL DEFAULT 0,
  delivery_fee     NUMERIC(10,2) NOT NULL DEFAULT 0,
  total_amount     NUMERIC(10,2) NOT NULL DEFAULT 0,
  currency         TEXT NOT NULL DEFAULT 'EUR',
  status           TEXT NOT NULL DEFAULT 'new',
  payment_status   TEXT NOT NULL DEFAULT 'pending',
  delivery_address TEXT NOT NULL DEFAULT '',
  delivery_date    DATE,
  notes            TEXT NOT NULL DEFAULT '',
  created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_items (
  id           SERIAL PRIMARY KEY,
  order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id   INTEGER REFERENCES products(id) ON DELETE SET NULL,
  product_name TEXT NOT NULL,
  quantity     INTEGER NOT NULL CHECK (quantity > 0),
  unit_price   NUMERIC(10,2) NOT NULL,
  line_total   NUMERIC(10,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS order_status_history (
  id         SERIAL PRIMARY KEY,
  order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  status     TEXT NOT NULL,
  note       TEXT NOT NULL DEFAULT '',
  changed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =====================================================================
-- ЯРУС 2 — ВРЕМЕННЫЙ / КЭШ (temporal): на проде ложится на Redis
-- =====================================================================

CREATE TABLE IF NOT EXISTS carts (
  id         SERIAL PRIMARY KEY,
  session_id TEXT NOT NULL UNIQUE,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cart_items (
  id         SERIAL PRIMARY KEY,
  cart_id    INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  quantity   INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
  added_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product_view_stats (
  product_id   INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
  views        INTEGER NOT NULL DEFAULT 0,
  window_start TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =====================================================================
-- Канонический сид (те же товары, что на L1–L6)
-- =====================================================================

INSERT INTO categories (name, slug, description) VALUES
  ('Розы', 'roses', 'Классические розы'),
  ('Тюльпаны', 'tulips', 'Весенние тюльпаны'),
  ('Букеты', 'bouquets', 'Готовые букеты')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO products (name, slug, description, price, currency, image, sku, category_id, stock, is_active, is_featured) VALUES
  ('Красная роза', 'red-rose', 'Классическая красная роза премиум класса', 1.50, 'EUR', 'images/rose.jpg', 'ROSE-RED-01',
     (SELECT id FROM categories WHERE slug='roses'), 50, TRUE, TRUE),
  ('Жёлтый тюльпан', 'yellow-tulip', 'Яркий жёлтый тюльпан', 0.80, 'EUR', 'images/tulip.jpg', 'TULIP-YEL-01',
     (SELECT id FROM categories WHERE slug='tulips'), 100, TRUE, FALSE),
  ('Пион', 'peony', 'Нежный ароматный пион', 2.20, 'EUR', 'images/peony.jpg', 'PEONY-01',
     (SELECT id FROM categories WHERE slug='bouquets'), 30, TRUE, TRUE)
ON CONFLICT (slug) DO NOTHING;
