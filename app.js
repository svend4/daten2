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
    const { name, phone, product_id, quantity } = req.body;

    db.run(
        'INSERT INTO orders (customer_name, phone, product_id, quantity) VALUES (?, ?, ?, ?)',
        [name, phone, product_id, quantity || 1],
        function(err) {
            if (err) {
                return res.status(500).send('Order error');
            }
            res.render('order', { orderId: this.lastID, name });
        }
    );
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
