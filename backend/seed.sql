-- Канонический сид: одинаковые товары и картинки на всех уровнях.

INSERT OR IGNORE INTO categories (name, slug, description) VALUES
    ('Розы',     'roses',    'Классические розы'),
    ('Тюльпаны', 'tulips',   'Весенние тюльпаны'),
    ('Букеты',   'bouquets', 'Готовые букеты');

INSERT OR IGNORE INTO products (name, slug, description, price, currency, image, sku, category_id, stock, is_active, is_featured) VALUES
    ('Красная роза', 'red-rose',   'Классическая красная роза премиум класса', 1.50, 'EUR', 'images/rose.jpg',  'ROSE-RED-01',  1, 50, 1, 1),
    ('Жёлтый тюльпан','yellow-tulip','Яркий жёлтый тюльпан',                     0.80, 'EUR', 'images/tulip.jpg', 'TULIP-YEL-01', 2, 100,1, 0),
    ('Пион',         'peony',      'Нежный ароматный пион',                     2.20, 'EUR', 'images/peony.jpg', 'PEONY-01',     3, 30, 1, 1);
