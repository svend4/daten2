// app.js
const express = require('express');
const path = require('path');
const sqlite3 = require('sqlite3').verbose();

const app = express();

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

// View engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Database
const db = new sqlite3.Database('./flowers.db');

// Routes
app.get('/', (req, res) => {
    db.all('SELECT * FROM products WHERE is_active = 1', [], (err, products) => {
        if (err) {
            return res.status(500).send('Database error');
        }
        res.render('index', { products });
    });
});

app.get('/product/:id', (req, res) => {
    db.get('SELECT * FROM products WHERE id = ?', [req.params.id], (err, product) => {
        if (err || !product) {
            return res.status(404).send('Product not found');
        }
        res.render('product', { product });
    });
});

app.post('/order', (req, res) => {
    const { name, phone, product_id } = req.body;
    const quantity = Math.max(1, parseInt(req.body.quantity, 10) || 1);

    if (!name || !product_id) {
        return res.status(400).send('Name and product are required');
    }

    // Серверный поиск цены и проверка остатка
    db.get('SELECT price, stock FROM products WHERE id = ?', [product_id], (err, product) => {
        if (err || !product) {
            return res.status(404).send('Product not found');
        }
        if (product.stock < quantity) {
            return res.status(400).send('Not enough stock');
        }

        db.serialize(() => {
            db.run('BEGIN');
            db.run(
                'INSERT INTO orders (customer_name, phone, status) VALUES (?, ?, ?)',
                [name, phone, 'new'],
                function (orderErr) {
                    if (orderErr) {
                        db.run('ROLLBACK');
                        return res.status(500).send('Order error');
                    }
                    const orderId = this.lastID;
                    db.run(
                        'INSERT INTO order_items (order_id, product_id, qty, price) VALUES (?, ?, ?, ?)',
                        [orderId, product_id, quantity, product.price],
                        (itemErr) => {
                            if (itemErr) {
                                db.run('ROLLBACK');
                                return res.status(500).send('Order error');
                            }
                            db.run('UPDATE products SET stock = stock - ? WHERE id = ?', [quantity, product_id]);
                            db.run('COMMIT');
                            res.render('order', { orderId, name });
                        }
                    );
                }
            );
        });
    });
});

// API endpoints
app.get('/api/products', (req, res) => {
    db.all('SELECT * FROM products WHERE is_active = 1', [], (err, products) => {
        if (err) {
            return res.status(500).json({ error: 'Database error' });
        }
        res.json(products);
    });
});

module.exports = app;
