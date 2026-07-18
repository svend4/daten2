from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import sqlite3
import os
import uuid
import init_db

# Гарантируем схему и сид (идемпотентно) из канонических schema.sql + seed.sql
init_db.init_db()

app = Flask(__name__, static_folder='static', static_url_path='')

# --- авторизация (пила коммерции L5): токены на основе SECRET_KEY ---
SECRET_KEY = os.environ.get('SECRET_KEY', 'insecure-dev-key-change-in-production')
_serializer = URLSafeTimedSerializer(SECRET_KEY, salt='auth')
TOKEN_MAX_AGE = 7 * 24 * 3600  # 7 дней


def make_token(user_id):
    return _serializer.dumps({'uid': user_id})


def current_user(db):
    """Возвращает строку пользователя по заголовку Authorization: Bearer <token>."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    try:
        data = _serializer.loads(auth[7:], max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return db.execute('SELECT id, email, name FROM users WHERE id = ?', (data.get('uid'),)).fetchone()

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

@app.get('/api/health')
def api_health():
    return jsonify({'ok': True, 'level': 5, 'stack': 'React+Flask'})


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

        # Если запрос авторизован — привязываем заказ к пользователю
        user = current_user(db)
        if user:
            db.execute('INSERT OR IGNORE INTO user_orders (user_id, order_id) VALUES (?, ?)',
                       (user['id'], order_id))

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


# ---------- авторизация (пила коммерции L5) ----------

@app.post('/api/auth/register')
def auth_register():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    name = (data.get('name') or '').strip()
    if not email or len(password) < 6:
        return jsonify({'error': 'email и пароль (мин. 6 символов) обязательны'}), 400
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)',
            (email, generate_password_hash(password), name)
        )
        db.commit()
        uid = cur.lastrowid
    except sqlite3.IntegrityError:
        db.close()
        return jsonify({'error': 'email уже зарегистрирован'}), 409
    db.close()
    return jsonify({'token': make_token(uid), 'user': {'email': email, 'name': name}}), 201


@app.post('/api/auth/login')
def auth_login():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    db = get_db()
    row = db.execute('SELECT id, email, name, password_hash FROM users WHERE email = ?', (email,)).fetchone()
    db.close()
    if not row or not check_password_hash(row['password_hash'], password):
        return jsonify({'error': 'неверные email или пароль'}), 401
    return jsonify({'token': make_token(row['id']), 'user': {'email': row['email'], 'name': row['name']}})


@app.get('/api/auth/me')
def auth_me():
    db = get_db()
    user = current_user(db)
    db.close()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    return jsonify({'email': user['email'], 'name': user['name']})


@app.get('/api/auth/orders')
def auth_orders():
    """История заказов текущего пользователя (только свои — защита от чужих)."""
    db = get_db()
    user = current_user(db)
    if not user:
        db.close()
        return jsonify({'error': 'unauthorized'}), 401
    rows = db.execute(
        '''SELECT o.order_number, o.total_amount, o.status, o.payment_status, o.created_at
           FROM orders o JOIN user_orders uo ON uo.order_id = o.id
           WHERE uo.user_id = ? ORDER BY o.id DESC''',
        (user['id'],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    app.run(port=int(os.environ.get('PORT', 5001)), debug=debug)
