from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import uuid
import init_db

# Гарантируем схему и сид (идемпотентно) из канонических schema.sql + seed.sql
init_db.init_db()

app = Flask(__name__, static_folder='static', static_url_path='')

# CORS ограничен явными origin'ами (по умолчанию только тот же origin).
# Список через запятую в CORS_ORIGINS; в single-service деплое фронт и API — один origin.
_cors_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
if _cors_origins:
    CORS(app, resources={r"/api/*": {"origins": _cors_origins}})


def get_db():
    conn = sqlite3.connect(os.environ.get('DATABASE_PATH', 'flowers.db'))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


# ---------- статика React ----------

@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')


# ---------- API ----------

@app.get('/api/products')
def products():
    db = get_db()
    rows = db.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.is_active = 1
           ORDER BY p.is_featured DESC, p.name'''
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.post('/api/orders')
def create_order():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    address = (data.get('address') or '').strip()
    items = data.get('items') or []

    if not name or not items:
        return jsonify({'error': 'name/items required'}), 400

    db = get_db()
    try:
        # Позиции с серверными ценами и снимком названия
        priced = []
        subtotal = 0.0
        for it in items:
            pid = int(it.get('product_id') or 0)
            qty = int(it.get('quantity') or it.get('qty') or 1)
            if qty < 1:
                continue
            p = db.execute('SELECT name, price FROM products WHERE id = ?', (pid,)).fetchone()
            if not p:
                continue
            line_total = float(p['price']) * qty
            subtotal += line_total
            priced.append((pid, p['name'], qty, float(p['price']), line_total))

        if not priced:
            return jsonify({'error': 'no valid items'}), 400

        cur = db.execute(
            'INSERT INTO customers (name, phone, email, address) VALUES (?, ?, ?, ?)',
            (name, phone, email, address)
        )
        customer_id = cur.lastrowid

        order_number = uuid.uuid4().hex
        db.execute(
            '''INSERT INTO orders
               (order_number, customer_id, subtotal, total_amount, delivery_address, status, payment_status)
               VALUES (?, ?, ?, ?, ?, 'new', 'pending')''',
            (order_number, customer_id, subtotal, subtotal, address)
        )
        order_id = db.execute(
            'SELECT id FROM orders WHERE order_number = ?', (order_number,)
        ).fetchone()['id']

        for pid, pname, qty, unit_price, line_total in priced:
            db.execute(
                '''INSERT INTO order_items
                   (order_id, product_id, product_name, quantity, unit_price, line_total)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (order_id, pid, pname, qty, unit_price, line_total)
            )
            db.execute('UPDATE products SET stock = stock - ? WHERE id = ?', (qty, pid))

        db.execute(
            "INSERT INTO order_status_history (order_id, status, note) VALUES (?, 'new', 'Заказ создан')",
            (order_id,)
        )
        db.commit()
        return jsonify({'order_number': order_number, 'total': subtotal}), 201
    except Exception:
        db.rollback()
        return jsonify({'error': 'order failed'}), 500
    finally:
        db.close()


@app.get('/api/orders/<order_number>')
def get_order(order_number):
    """Заказ по непубличному токену (защита от перебора id)."""
    db = get_db()
    order = db.execute(
        '''SELECT o.*, c.name AS customer_name, c.phone
           FROM orders o JOIN customers c ON c.id = o.customer_id
           WHERE o.order_number = ?''',
        (order_number,)
    ).fetchone()
    if not order:
        db.close()
        return jsonify({'error': 'not found'}), 404
    items = db.execute(
        'SELECT product_name, quantity, unit_price, line_total FROM order_items WHERE order_id = ?',
        (order['id'],)
    ).fetchall()
    db.close()
    return jsonify({'order': dict(order), 'items': [dict(i) for i in items]})


if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    app.run(port=int(os.environ.get('PORT', 5001)), debug=debug)
