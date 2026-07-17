# database.py — слой доступа к данным (каноническая богатая схема).
import os
import uuid
import sqlite3

DATABASE = os.environ.get('DATABASE_PATH', 'flowers.db')


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


# ---------- каталог (durable) ----------

def get_all_products():
    conn = get_db()
    rows = conn.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.is_active = 1 ORDER BY p.is_featured DESC, p.name'''
    ).fetchall()
    conn.close()
    return rows


def get_products_by_category(category_id):
    conn = get_db()
    rows = conn.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.is_active = 1 AND p.category_id = ? ORDER BY p.name''',
        (category_id,)
    ).fetchall()
    conn.close()
    return rows


def search_products(query):
    conn = get_db()
    rows = conn.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.is_active = 1 AND p.name LIKE ? ORDER BY p.name''',
        (f'%{query}%',)
    ).fetchall()
    conn.close()
    return rows


def get_product_by_id(product_id):
    conn = get_db()
    row = conn.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.id = ?''',
        (product_id,)
    ).fetchone()
    conn.close()
    return row


def get_all_categories():
    conn = get_db()
    rows = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return rows


# ---------- оформление заказа (durable) ----------

def create_order(customer_data, cart_items):
    """Создаёт покупателя + заказ + позиции + запись истории.

    Возвращает (order_number, total_amount). order_number — непубличный токен,
    по нему открывается страница заказа (защита от перебора по id).
    """
    conn = get_db()
    try:
        cur = conn.cursor()

        # Позиции с серверными ценами и снимком названия
        priced = []
        subtotal = 0.0
        for item in cart_items:
            product = cur.execute(
                'SELECT name, price, stock FROM products WHERE id = ?',
                (item['product_id'],)
            ).fetchone()
            if not product:
                continue
            qty = int(item['quantity'])
            if qty < 1:
                continue
            line_total = product['price'] * qty
            subtotal += line_total
            priced.append((item['product_id'], product['name'], qty, product['price'], line_total))

        if not priced:
            raise ValueError('Корзина пуста или товары недоступны')

        # Покупатель (отдельная сущность)
        cur.execute(
            '''INSERT INTO customers (name, phone, email, address, city, postal_code)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (customer_data.get('name', ''), customer_data.get('phone', ''),
             customer_data.get('email', ''), customer_data.get('address', ''),
             customer_data.get('city', ''), customer_data.get('postal_code', ''))
        )
        customer_id = cur.lastrowid

        order_number = uuid.uuid4().hex
        total_amount = subtotal  # discount/delivery_fee = 0 для демо
        cur.execute(
            '''INSERT INTO orders
               (order_number, customer_id, subtotal, total_amount, delivery_address, status, payment_status)
               VALUES (?, ?, ?, ?, ?, 'new', 'pending')''',
            (order_number, customer_id, subtotal, total_amount, customer_data.get('address', ''))
        )
        order_id = cur.lastrowid

        for product_id, product_name, qty, unit_price, line_total in priced:
            cur.execute(
                '''INSERT INTO order_items
                   (order_id, product_id, product_name, quantity, unit_price, line_total)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (order_id, product_id, product_name, qty, unit_price, line_total)
            )
            cur.execute('UPDATE products SET stock = stock - ? WHERE id = ?', (qty, product_id))

        cur.execute(
            "INSERT INTO order_status_history (order_id, status, note) VALUES (?, 'new', 'Заказ создан')",
            (order_id,)
        )

        conn.commit()
        return order_number, total_amount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_order_by_number(order_number):
    conn = get_db()
    order = conn.execute(
        '''SELECT o.*, c.name AS customer_name, c.phone, c.email
           FROM orders o JOIN customers c ON c.id = o.customer_id
           WHERE o.order_number = ?''',
        (order_number,)
    ).fetchone()
    if not order:
        conn.close()
        return None
    items = conn.execute(
        'SELECT product_name, quantity, unit_price, line_total FROM order_items WHERE order_id = ?',
        (order['id'],)
    ).fetchall()
    conn.close()
    return {
        'order': dict(order),
        'items': [dict(i) for i in items],
        'total': order['total_amount'],
    }
