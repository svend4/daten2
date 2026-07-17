# database.py
import sqlite3
import os

DATABASE = os.environ.get('DATABASE_PATH', 'flowers.db')


def get_db():
    """Соединение с БД; строки доступны как словари."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_products():
    conn = get_db()
    rows = conn.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p
           LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.is_active = 1
           ORDER BY p.name'''
    ).fetchall()
    conn.close()
    return rows


def get_products_by_category(category_id):
    conn = get_db()
    rows = conn.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p
           LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.is_active = 1 AND p.category_id = ?
           ORDER BY p.name''',
        (category_id,)
    ).fetchall()
    conn.close()
    return rows


def search_products(query):
    conn = get_db()
    rows = conn.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p
           LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.is_active = 1 AND p.name LIKE ?
           ORDER BY p.name''',
        (f'%{query}%',)
    ).fetchall()
    conn.close()
    return rows


def get_product_by_id(product_id):
    conn = get_db()
    row = conn.execute(
        '''SELECT p.*, c.name AS category_name
           FROM products p
           LEFT JOIN categories c ON c.id = p.category_id
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


def create_order(customer_data, cart_items):
    """Создаёт заказ и позиции. Возвращает (order_id, total_amount).

    Схема БД хранит имя и телефон прямо в orders; email/адрес используются
    только в процессе оформления. Цена берётся с сервера, остаток списывается.
    """
    conn = get_db()
    try:
        cur = conn.cursor()

        # Собрать позиции с серверными ценами и посчитать сумму
        priced_items = []
        total = 0.0
        for item in cart_items:
            product = cur.execute(
                'SELECT price, stock FROM products WHERE id = ?',
                (item['product_id'],)
            ).fetchone()
            if not product:
                continue
            qty = int(item['quantity'])
            if qty < 1:
                continue
            total += product['price'] * qty
            priced_items.append((item['product_id'], qty, product['price']))

        if not priced_items:
            raise ValueError('Корзина пуста или товары недоступны')

        cur.execute(
            'INSERT INTO orders (customer_name, phone, status) VALUES (?, ?, ?)',
            (customer_data['name'], customer_data['phone'], 'new')
        )
        order_id = cur.lastrowid

        for product_id, qty, price in priced_items:
            cur.execute(
                'INSERT INTO order_items (order_id, product_id, qty, price) VALUES (?, ?, ?, ?)',
                (order_id, product_id, qty, price)
            )
            cur.execute(
                'UPDATE products SET stock = stock - ? WHERE id = ?',
                (qty, product_id)
            )

        conn.commit()
        return order_id, total
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_order_by_id(order_id):
    conn = get_db()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        conn.close()
        return None
    items = conn.execute(
        '''SELECT oi.qty, oi.price, p.name, p.image
           FROM order_items oi
           JOIN products p ON p.id = oi.product_id
           WHERE oi.order_id = ?''',
        (order_id,)
    ).fetchall()
    conn.close()
    total = sum(i['qty'] * i['price'] for i in items)
    return {
        'order': dict(order),
        'items': [dict(i) for i in items],
        'total': total,
    }
