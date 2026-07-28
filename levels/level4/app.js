// app.js — конфигурация Express-приложения (маршруты, шаблоны, база данных)
// server.js подключает этот файл и вызывает app.listen()

const path = require('path');
const express = require('express');
const sqlite3 = require('sqlite3');

const app = express();

// --- Шаблоны EJS ---
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// --- Разбор данных HTML-формы (POST /order) ---
app.use(express.urlencoded({ extended: false }));

// --- Статика: шаблоны ссылаются на /public/style.css, поэтому монтируем по /public ---
app.use('/public', express.static(path.join(__dirname, 'public')));

// --- База данных SQLite ---
const db = new sqlite3.Database(path.join(__dirname, 'flowers.db'));

// GET / — каталог товаров
app.get('/', (req, res, next) => {
    db.all(
        'SELECT id, name, description, price FROM products WHERE is_active = 1 ORDER BY id',
        (err, products) => {
            if (err) return next(err);
            res.render('index', { products });
        }
    );
});

// GET /product/:id — карточка одного товара
app.get('/product/:id', (req, res, next) => {
    db.get(
        'SELECT id, name, description, price FROM products WHERE id = ?',
        [req.params.id],
        (err, product) => {
            if (err) return next(err);
            if (!product) return res.status(404).render('404');
            res.render('product', { product });
        }
    );
});

// POST /order — оформление заказа: orders + order_items
app.post('/order', (req, res, next) => {
    const name = (req.body.name || '').trim();
    const phone = (req.body.phone || '').trim();
    const productId = Number(req.body.product_id);

    if (!name || !productId) {
        return res.status(400).send('Укажите имя и товар');
    }

    db.get('SELECT id, price FROM products WHERE id = ?', [productId], (err, product) => {
        if (err) return next(err);
        if (!product) return res.status(404).render('404');

        db.run(
            'INSERT INTO orders (customer_name, phone) VALUES (?, ?)',
            [name, phone],
            function (err) {
                if (err) return next(err);
                const orderId = this.lastID;

                db.run(
                    'INSERT INTO order_items (order_id, product_id, qty, price) VALUES (?, ?, 1, ?)',
                    [orderId, product.id, product.price],
                    (err) => {
                        if (err) return next(err);
                        res.render('order', { order_id: orderId });
                    }
                );
            }
        );
    });
});

// 404 — страница не найдена
app.use((req, res) => {
    res.status(404).render('404');
});

module.exports = app;
