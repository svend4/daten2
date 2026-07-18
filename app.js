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

// ============= ЕДИНЫЙ JSON API (канонический контракт) =============

// promise-обёртки над sqlite3 для читаемого async-кода
const dbGet = (sql, p = []) => new Promise((res, rej) => db.get(sql, p, (e, r) => (e ? rej(e) : res(r))));
const dbAll = (sql, p = []) => new Promise((res, rej) => db.all(sql, p, (e, r) => (e ? rej(e) : res(r))));
const dbRun = (sql, p = []) => new Promise((res, rej) => db.run(sql, p, function (e) { e ? rej(e) : res(this); }));

app.get('/api/health', (req, res) => res.json({ ok: true, level: 4, stack: 'Express' }));

app.get('/api/products', (req, res) => {
    db.all(
        `SELECT p.*, c.name AS category_name
         FROM products p LEFT JOIN categories c ON c.id = p.category_id
         WHERE p.is_active = 1
         ORDER BY p.is_featured DESC, p.name`,
        [],
        (err, products) => {
            if (err) return res.status(500).json({ error: 'Database error' });
            res.json(products);
        }
    );
});

app.post('/api/orders', async (req, res) => {
    const { name, phone, email, address } = req.body || {};
    const items = Array.isArray(req.body?.items) ? req.body.items : [];
    if (!name || items.length === 0) {
        return res.status(400).json({ error: 'name/items required' });
    }
    try {
        const priced = [];
        let subtotal = 0;
        for (const it of items) {
            const qty = Math.max(1, parseInt(it.quantity ?? it.qty, 10) || 1);
            const p = await dbGet('SELECT name, price FROM products WHERE id = ?', [it.product_id]);
            if (!p) continue;
            const lineTotal = p.price * qty;
            subtotal += lineTotal;
            priced.push({ id: it.product_id, name: p.name, qty, price: p.price, lineTotal });
        }
        if (priced.length === 0) return res.status(400).json({ error: 'no valid items' });

        const orderNumber = crypto.randomUUID().replace(/-/g, '');
        await dbRun('BEGIN');
        try {
            const cust = await dbRun('INSERT INTO customers (name, phone, email, address) VALUES (?, ?, ?, ?)',
                [name, phone || '', email || '', address || '']);
            const ord = await dbRun(
                `INSERT INTO orders (order_number, customer_id, subtotal, total_amount, delivery_address, status, payment_status)
                 VALUES (?, ?, ?, ?, ?, 'new', 'pending')`,
                [orderNumber, cust.lastID, subtotal, subtotal, address || '']);
            for (const it of priced) {
                await dbRun(
                    `INSERT INTO order_items (order_id, product_id, product_name, quantity, unit_price, line_total)
                     VALUES (?, ?, ?, ?, ?, ?)`,
                    [ord.lastID, it.id, it.name, it.qty, it.price, it.lineTotal]);
                await dbRun('UPDATE products SET stock = stock - ? WHERE id = ?', [it.qty, it.id]);
            }
            await dbRun("INSERT INTO order_status_history (order_id, status, note) VALUES (?, 'new', 'Заказ создан')", [ord.lastID]);
            await dbRun('COMMIT');
        } catch (txErr) {
            await dbRun('ROLLBACK');
            throw txErr;
        }
        res.status(201).json({ order_number: orderNumber, total: subtotal });
    } catch (e) {
        res.status(400).json({ error: 'order failed' });
    }
});

app.get('/api/orders/:orderNumber', async (req, res) => {
    try {
        const order = await dbGet(
            `SELECT o.*, c.name AS customer_name, c.phone
             FROM orders o JOIN customers c ON c.id = o.customer_id
             WHERE o.order_number = ?`,
            [req.params.orderNumber]);
        if (!order) return res.status(404).json({ error: 'not found' });
        const items = await dbAll(
            'SELECT product_name, quantity, unit_price, line_total FROM order_items WHERE order_id = ?',
            [order.id]);
        res.json({ order, items });
    } catch (e) {
        res.status(500).json({ error: 'Database error' });
    }
});

module.exports = app;
