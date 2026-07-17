// app.js — приложение на канонической богатой схеме
const express = require('express');
const path = require('path');
const crypto = require('crypto');
const sqlite3 = require('sqlite3').verbose();

const app = express();

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
// Шаблоны ссылаются на /public/style.css — монтируем статику под /public
app.use('/public', express.static(path.join(__dirname, 'public')));

// View engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Database
const DB_PATH = process.env.DATABASE_PATH || path.join(__dirname, 'flowers.db');
const db = new sqlite3.Database(DB_PATH);
db.run('PRAGMA foreign_keys = ON');

// Каталог
app.get('/', (req, res) => {
    db.all(
        `SELECT p.*, c.name AS category_name
         FROM products p LEFT JOIN categories c ON c.id = p.category_id
         WHERE p.is_active = 1
         ORDER BY p.is_featured DESC, p.name`,
        [],
        (err, products) => {
            if (err) return res.status(500).send('Database error');
            res.render('index', { products });
        }
    );
});

// Страница товара
app.get('/product/:id', (req, res) => {
    db.get(
        `SELECT p.*, c.name AS category_name
         FROM products p LEFT JOIN categories c ON c.id = p.category_id
         WHERE p.id = ?`,
        [req.params.id],
        (err, product) => {
            if (err || !product) return res.status(404).send('Product not found');
            res.render('product', { product });
        }
    );
});

// Оформление заказа (богатая схема: customers + order_number + snapshot + история)
app.post('/order', (req, res) => {
    const { name, phone, product_id } = req.body;
    const quantity = Math.max(1, parseInt(req.body.quantity, 10) || 1);

    if (!name || !product_id) {
        return res.status(400).send('Name and product are required');
    }

    db.get('SELECT name, price, stock FROM products WHERE id = ?', [product_id], (err, product) => {
        if (err || !product) return res.status(404).send('Product not found');
        if (product.stock < quantity) return res.status(400).send('Not enough stock');

        const orderNumber = crypto.randomUUID().replace(/-/g, '');
        const lineTotal = product.price * quantity;

        db.serialize(() => {
            db.run('BEGIN');
            db.run(
                'INSERT INTO customers (name, phone) VALUES (?, ?)',
                [name, phone || ''],
                function (custErr) {
                    if (custErr) { db.run('ROLLBACK'); return res.status(500).send('Order error'); }
                    const customerId = this.lastID;
                    db.run(
                        `INSERT INTO orders
                         (order_number, customer_id, subtotal, total_amount, status, payment_status)
                         VALUES (?, ?, ?, ?, 'new', 'pending')`,
                        [orderNumber, customerId, lineTotal, lineTotal],
                        function (orderErr) {
                            if (orderErr) { db.run('ROLLBACK'); return res.status(500).send('Order error'); }
                            const orderId = this.lastID;
                            db.run(
                                `INSERT INTO order_items
                                 (order_id, product_id, product_name, quantity, unit_price, line_total)
                                 VALUES (?, ?, ?, ?, ?, ?)`,
                                [orderId, product_id, product.name, quantity, product.price, lineTotal],
                                (itemErr) => {
                                    if (itemErr) { db.run('ROLLBACK'); return res.status(500).send('Order error'); }
                                    db.run('UPDATE products SET stock = stock - ? WHERE id = ?', [quantity, product_id]);
                                    db.run(
                                        "INSERT INTO order_status_history (order_id, status, note) VALUES (?, 'new', 'Заказ создан')",
                                        [orderId]
                                    );
                                    db.run('COMMIT');
                                    // PRG: страница заказа по непубличному токену
                                    res.redirect(`/order/${orderNumber}`);
                                }
                            );
                        }
                    );
                }
            );
        });
    });
});

// Страница заказа по непубличному order_number (защита от перебора id)
app.get('/order/:orderNumber', (req, res) => {
    db.get(
        `SELECT o.*, c.name AS customer_name, c.phone
         FROM orders o JOIN customers c ON c.id = o.customer_id
         WHERE o.order_number = ?`,
        [req.params.orderNumber],
        (err, order) => {
            if (err || !order) return res.status(404).send('Order not found');
            db.all(
                'SELECT product_name, quantity, unit_price, line_total FROM order_items WHERE order_id = ?',
                [order.id],
                (itemsErr, items) => {
                    if (itemsErr) return res.status(500).send('Database error');
                    res.render('order', { order, items });
                }
            );
        }
    );
});

// API
app.get('/api/products', (req, res) => {
    db.all('SELECT * FROM products WHERE is_active = 1', [], (err, products) => {
        if (err) return res.status(500).json({ error: 'Database error' });
        res.json(products);
    });
});

module.exports = app;
