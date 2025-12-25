# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash
from config import Config
import database as db

app = Flask(__name__)
app.config.from_object(Config)

# Инициализация сессий для корзины
from flask_session import Session
Session(app)

# ============= ГЛАВНАЯ СТРАНИЦА =============

@app.route('/')
def index():
    """Главная страница с каталогом товаров"""
    
    # Получить параметры из URL
    search_query = request.args.get('search', '').strip()
    category_id = request.args.get('category', type=int)
    
    # Получить товары
    if search_query:
        products = db.search_products(search_query)
        page_title = f'Поиск: "{search_query}"'
    elif category_id:
        products = db.get_products_by_category(category_id)
        page_title = 'Товары в категории'
    else:
        products = db.get_all_products()
        page_title = 'Каталог цветов'
    
    # Получить категории для меню
    categories = db.get_all_categories()
    
    return render_template('index.html',
                          products=products,
                          categories=categories,
                          page_title=page_title,
                          search_query=search_query,
                          current_category=category_id)

# ============= СТРАНИЦА ТОВАРА =============

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    """Детальная страница товара"""
    product = db.get_product_by_id(product_id)
    
    if not product:
        flash('Товар не найден', 'error')
        return redirect(url_for('index'))
    
    return render_template('product.html', product=product)

# ============= КОРЗИНА =============

@app.route('/cart')
def cart():
    """Страница корзины"""
    cart_items = session.get('cart', [])
    
    # Получить полную информацию о товарах в корзине
    cart_products = []
    total = 0
    
    for item in cart_items:
        product = db.get_product_by_id(item['product_id'])
        if product:
            cart_product = dict(product)
            cart_product['quantity'] = item['quantity']
            cart_product['subtotal'] = product['price'] * item['quantity']
            cart_products.append(cart_product)
            total += cart_product['subtotal']
    
    return render_template('cart.html', cart_items=cart_products, total=total)

@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    """Добавить товар в корзину"""
    quantity = request.form.get('quantity', 1, type=int)
    
    if quantity < 1:
        flash('Неверное количество', 'error')
        return redirect(url_for('product_detail', product_id=product_id))
    
    # Проверить наличие товара
    product = db.get_product_by_id(product_id)
    if not product:
        flash('Товар не найден', 'error')
        return redirect(url_for('index'))
    
    if product['stock'] < quantity:
        flash(f'К сожалению, в наличии только {product["stock"]} шт.', 'error')
        return redirect(url_for('product_detail', product_id=product_id))
    
    # Инициализировать корзину если её нет
    if 'cart' not in session:
        session['cart'] = []
    
    # Проверить, есть ли товар уже в корзине
    cart = session['cart']
    found = False
    
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] += quantity
            found = True
            break
    
    if not found:
        cart.append({
            'product_id': product_id,
            'quantity': quantity
        })
    
    session['cart'] = cart
    session.modified = True
    
    flash(f'Товар "{product["name"]}" добавлен в корзину!', 'success')
    return redirect(url_for('cart'))

@app.route('/cart/remove/<int:product_id>')
def remove_from_cart(product_id):
    """Удалить товар из корзины"""
    if 'cart' in session:
        cart = session['cart']
        session['cart'] = [item for item in cart if item['product_id'] != product_id]
        session.modified = True
        flash('Товар удален из корзины', 'info')
    
    return redirect(url_for('cart'))

@app.route('/cart/clear')
def clear_cart():
    """Очистить корзину"""
    session.pop('cart', None)
    flash('Корзина очищена', 'info')
    return redirect(url_for('cart'))

# ============= ОФОРМЛЕНИЕ ЗАКАЗА =============

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """Оформление заказа"""
    
    # Проверить, есть ли товары в корзине
    cart_items = session.get('cart', [])
    if not cart_items:
        flash('Ваша корзина пуста', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # Получить данные из формы
        customer_data = {
            'name': request.form.get('name'),
            'phone': request.form.get('phone'),
            'email': request.form.get('email', ''),
            'address': request.form.get('address')
        }
        
        # Валидация
        if not customer_data['name'] or not customer_data['phone'] or not customer_data['address']:
            flash('Пожалуйста, заполните все обязательные поля', 'error')
            return redirect(url_for('checkout'))
        
        try:
            # Создать заказ
            order_id, total_amount = db.create_order(customer_data, cart_items)
            
            # Очистить корзину
            session.pop('cart', None)
            
            flash(f'Заказ #{order_id} успешно оформлен!', 'success')
            return redirect(url_for('order_success', order_id=order_id))
            
        except Exception as e:
            flash(f'Ошибка при создании заказа: {str(e)}', 'error')
            return redirect(url_for('checkout'))
    
    # GET запрос - показать форму
    # Получить товары для отображения
    cart_products = []
    total = 0
    
    for item in cart_items:
        product = db.get_product_by_id(item['product_id'])
        if product:
            cart_product = dict(product)
            cart_product['quantity'] = item['quantity']
            cart_product['subtotal'] = product['price'] * item['quantity']
            cart_products.append(cart_product)
            total += cart_product['subtotal']
    
    return render_template('checkout.html', cart_items=cart_products, total=total)

@app.route('/order/<int:order_id>')
def order_success(order_id):
    """Страница успешного заказа"""
    order_data = db.get_order_by_id(order_id)
    
    if not order_data:
        flash('Заказ не найден', 'error')
        return redirect(url_for('index'))
    
    return render_template('order_success.html', order_data=order_data)

# ============= ОБРАБОТЧИКИ ОШИБОК =============

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template('500.html'), 500

# ============= ЗАПУСК ПРИЛОЖЕНИЯ =============

if __name__ == '__main__':
    app.run(debug=Config.DEBUG, host='0.0.0.0', port=5000)
