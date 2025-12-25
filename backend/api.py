from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

def get_db():
    conn = sqlite3.connect('flowers.db')
    conn.row_factory = sqlite3.Row
    return conn

# Serve React app
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

@app.get('/api/products')
def products():
    db = get_db()
    rows = db.execute('SELECT * FROM products WHERE is_active = 1 ORDER BY id DESC').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.post('/api/orders')
def create_order():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()
    items = data.get('items') or []

    if not name or not items:
        return jsonify({'error': 'name/items required'}), 400

    db = get_db()
    cur = db.execute('INSERT INTO orders (customer_name, phone) VALUES (?, ?)', (name, phone))
    order_id = cur.lastrowid

    for it in items:
        pid = int(it.get('product_id') or 0)
        qty = int(it.get('qty') or 1)
        p = db.execute('SELECT price FROM products WHERE id = ?', (pid,)).fetchone()
        price = float(p['price']) if p else 0.0
        db.execute('INSERT INTO order_items (order_id, product_id, qty, price) VALUES (?, ?, ?, ?)',
                   (order_id, pid, qty, price))

    db.commit()
    db.close()
    return jsonify({'order_id': order_id})

if __name__ == '__main__':
    app.run(port=5001, debug=True)
