# database.py — работа с базой данных SQLite
import sqlite3

from config import Config


def get_connection():
    """Открыть соединение с базой. Строки возвращаются как sqlite3.Row (как словарь)."""
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Дополнить схему недостающими колонками (данные не удаляются).

    В файле flowers.db таблица orders изначально содержит только
    customer_name, phone, created_at, status. Для оформления заказа нам нужны
    ещё email, address и сумма заказа — добавляем их через ALTER TABLE.
    """
    conn = get_connection()
    existing = [row['name'] for row in conn.execute('PRAGMA table_info(orders)')]

    new_columns = {
        'email': "TEXT DEFAULT ''",
        'address': "TEXT DEFAULT ''",
        'total_amount': 'REAL DEFAULT 0',
    }
    for column, definition in new_columns.items():
        if column not in existing:
            conn.execute(f'ALTER TABLE orders ADD COLUMN {column} {definition}')

    conn.commit()
    conn.close()


# ============= ТОВАРЫ =============

def get_all_products():
    """Все товары в наличии (активные)."""
    conn = get_connection()
    products = conn.execute(
        'SELECT * FROM products WHERE is_active = 1 ORDER BY id'
    ).fetchall()
    conn.close()
    return products


def get_product_by_id(product_id):
    """Один товар по id или None."""
    conn = get_connection()
    product = conn.execute(
        'SELECT * FROM products WHERE id = ?', (product_id,)
    ).fetchone()
    conn.close()
    return product


def get_products_by_category(category_id):
    """Товары одной категории."""
    conn = get_connection()
    products = conn.execute(
        'SELECT * FROM products WHERE is_active = 1 AND category_id = ? ORDER BY id',
        (category_id,)
    ).fetchall()
    conn.close()
    return products


def get_all_categories():
    """Все категории для меню."""
    conn = get_connection()
    categories = conn.execute('SELECT * FROM categories ORDER BY id').fetchall()
    conn.close()
    return categories


def search_products(query):
    """Поиск по названию и описанию."""
    conn = get_connection()
    pattern = f'%{query}%'
    products = conn.execute(
        'SELECT * FROM products '
        'WHERE is_active = 1 AND (name LIKE ? OR description LIKE ?) '
        'ORDER BY id',
        (pattern, pattern)
    ).fetchall()
    conn.close()
    return products


# ============= ЗАКАЗЫ =============

def create_order(customer_data, cart_items):
    """Создать заказ. Возвращает (order_id, total_amount).

    customer_data: {'name', 'phone', 'email', 'address'}
    cart_items:    [{'product_id': 1, 'quantity': 2}, ...]
    """
    conn = get_connection()

    # Считаем сумму по ценам из базы (а не из корзины — так надёжнее)
    total_amount = 0
    items = []
    for item in cart_items:
        product = conn.execute(
            'SELECT * FROM products WHERE id = ?', (item['product_id'],)
        ).fetchone()
        if product is None:
            continue
        quantity = int(item['quantity'])
        total_amount += product['price'] * quantity
        items.append((product['id'], quantity, product['price']))

    if not items:
        conn.close()
        raise ValueError('Корзина пуста')

    cursor = conn.execute(
        'INSERT INTO orders (customer_name, phone, email, address, total_amount, status) '
        "VALUES (?, ?, ?, ?, ?, 'new')",
        (
            customer_data['name'],
            customer_data.get('phone', ''),
            customer_data.get('email', ''),
            customer_data.get('address', ''),
            total_amount,
        )
    )
    order_id = cursor.lastrowid

    for product_id, quantity, price in items:
        conn.execute(
            'INSERT INTO order_items (order_id, product_id, qty, price) VALUES (?, ?, ?, ?)',
            (order_id, product_id, quantity, price)
        )
        # Уменьшаем остаток на складе
        conn.execute(
            'UPDATE products SET stock = MAX(stock - ?, 0) WHERE id = ?',
            (quantity, product_id)
        )

    conn.commit()
    conn.close()
    return order_id, total_amount


def get_order_by_id(order_id):
    """Заказ вместе с его товарами: {'order': ..., 'items': [...]} или None."""
    conn = get_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()

    if order is None:
        conn.close()
        return None

    items = conn.execute(
        'SELECT order_items.qty, order_items.price, products.name '
        'FROM order_items JOIN products ON products.id = order_items.product_id '
        'WHERE order_items.order_id = ?',
        (order_id,)
    ).fetchall()
    conn.close()

    return {'order': order, 'items': items}


# Проверяем/дополняем схему при импорте модуля
init_db()
