CREATE TABLE IF NOT EXISTS products (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  price NUMERIC(10,2) NOT NULL,
  image TEXT,
  stock INTEGER DEFAULT 0,
  is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS orders (
  id SERIAL PRIMARY KEY,
  customer_name TEXT NOT NULL,
  phone TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  status TEXT DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS order_items (
  id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL,
  qty INTEGER NOT NULL DEFAULT 1,
  price NUMERIC(10,2) NOT NULL
);

INSERT INTO products (name, description, price, image, stock, is_active)
VALUES
('Красная роза', 'Классическая красная роза.', 7.90, NULL, 50, TRUE),
('Букет тюльпанов', 'Букет из 9 тюльпанов.', 19.90, NULL, 30, TRUE),
('Пион (шт.)', 'Пышный пион.', 9.50, NULL, 25, TRUE)
ON CONFLICT DO NOTHING;
