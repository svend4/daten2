<?php
// init_db.php - Запустить ОДИН РАЗ для создания базы

$db = new SQLite3('flowers.db');

// Создать таблицу категорий
$db->exec('
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )
');

// Создать таблицу товаров
$db->exec('
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        category_id INTEGER,
        photo_path TEXT,
        stock INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )
');

// Создать таблицу клиентов
$db->exec('
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT,
        address TEXT
    )
');

// Создать таблицу заказов
$db->exec('
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        total_amount REAL NOT NULL,
        status TEXT DEFAULT "new",
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
');

// Создать таблицу товаров в заказе
$db->exec('
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL
    )
');

// Добавить категории
$db->exec("INSERT INTO categories (name) VALUES ('Розы')");
$db->exec("INSERT INTO categories (name) VALUES ('Тюльпаны')");
$db->exec("INSERT INTO categories (name) VALUES ('Букеты')");

// Добавить товары
$db->exec("
    INSERT INTO products (name, description, price, category_id, photo_path, stock) VALUES
    ('Красная роза', 'Классическая красная роза премиум класса', 150.00, 1, 'images/rose-red.jpg', 50),
    ('Белая роза', 'Нежная белая роза', 140.00, 1, 'images/rose-white.jpg', 30),
    ('Желтый тюльпан', 'Яркий желтый тюльпан', 80.00, 2, 'images/tulip-yellow.jpg', 100),
    ('Розовый тюльпан', 'Нежно-розовый тюльпан', 85.00, 2, 'images/tulip-yellow.jpg', 80),
    ('Букет Романтика', 'Букет из 15 красных роз', 2200.00, 3, 'images/bouquet.jpg', 10)
");

echo "✅ База данных создана успешно!<br>";
echo "Теперь можно открыть index.php";

$db->close();
?>