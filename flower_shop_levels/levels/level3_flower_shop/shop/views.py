# shop/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView
from django.contrib import messages
from django.db.models import Q
from decimal import Decimal

from .models import Product, Category, Order, OrderItem, Customer
from .forms import AddToCartForm, CheckoutForm


class ProductListView(ListView):
    """Список товаров"""
    model = Product
    template_name = 'shop/index.html'
    context_object_name = 'products'
    paginate_by = 12
    
    def get_queryset(self):
        queryset = Product.objects.filter(is_active=True).select_related('category')
        
        # Поиск
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query)
            )
        
        # Фильтр по категории
        category_slug = self.request.GET.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
        context['current_category'] = self.request.GET.get('category', '')
        return context


class ProductDetailView(DetailView):
    """Детальная страница товара"""
    model = Product
    template_name = 'shop/product_detail.html'
    context_object_name = 'product'
    
    def get_queryset(self):
        return Product.objects.filter(is_active=True).select_related('category')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = AddToCartForm()
        return context


def add_to_cart(request, slug):
    """Добавить товар в корзину"""
    product = get_object_or_404(Product, slug=slug, is_active=True)
    
    if request.method == 'POST':
        form = AddToCartForm(request.POST)
        if form.is_valid():
            quantity = form.cleaned_data['quantity']
            
            # Проверить наличие
            if product.stock < quantity:
                messages.error(
                    request,
                    f'К сожалению, в наличии только {product.stock} шт.'
                )
                return redirect('shop:product_detail', slug=slug)
            
            # Получить или создать корзину в сессии
            cart = request.session.get('cart', {})
            
            # Добавить товар
            if slug in cart:
                cart[slug]['quantity'] += quantity
            else:
                cart[slug] = {
                    'product_id': product.id,
                    'name': product.name,
                    'price': str(product.price),
                    'quantity': quantity,
                    'image': product.image.url if product.image else None,
                }
            
            request.session['cart'] = cart
            request.session.modified = True
            
            messages.success(
                request,
                f'Товар "{product.name}" добавлен в корзину!'
            )
            return redirect('shop:cart')
    
    return redirect('shop:product_detail', slug=slug)


def cart_view(request):
    """Просмотр корзины"""
    cart = request.session.get('cart', {})
    
    # Получить полную информацию о товарах
    cart_items = []
    total = Decimal('0.00')
    
    for slug, item in cart.items():
        try:
            product = Product.objects.get(slug=slug, is_active=True)
            price = Decimal(item['price'])
            quantity = item['quantity']
            subtotal = price * quantity
            
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'price': price,
                'subtotal': subtotal,
            })
            total += subtotal
        except Product.DoesNotExist:
            # Удалить несуществующий товар из корзины
            del cart[slug]
            request.session.modified = True
    
    context = {
        'cart_items': cart_items,
        'total': total,
    }
    return render(request, 'shop/cart.html', context)


def update_cart(request, slug):
    """Обновить количество товара в корзине"""
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        cart = request.session.get('cart', {})
        
        if slug in cart:
            product = get_object_or_404(Product, slug=slug)
            if quantity > 0 and quantity <= product.stock:
                cart[slug]['quantity'] = quantity
                request.session['cart'] = cart
                request.session.modified = True
                messages.success(request, 'Корзина обновлена')
            else:
                messages.error(request, 'Неверное количество')
    
    return redirect('shop:cart')


def remove_from_cart(request, slug):
    """Удалить товар из корзины"""
    cart = request.session.get('cart', {})
    
    if slug in cart:
        product_name = cart[slug]['name']
        del cart[slug]
        request.session['cart'] = cart
        request.session.modified = True
        messages.info(request, f'Товар "{product_name}" удалён из корзины')
    
    return redirect('shop:cart')


def clear_cart(request):
    """Очистить корзину"""
    request.session['cart'] = {}
    request.session.modified = True
    messages.info(request, 'Корзина очищена')
    return redirect('shop:cart')


def checkout(request):
    """Оформление заказа"""
    cart = request.session.get('cart', {})
    
    if not cart:
        messages.error(request, 'Ваша корзина пуста')
        return redirect('shop:index')
    
    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            try:
                # Создать клиента
                customer = Customer.objects.create(
                    name=form.cleaned_data['name'],
                    phone=form.cleaned_data['phone'],
                    email=form.cleaned_data['email'],
                    address=form.cleaned_data['address'],
                )
                
                # Рассчитать сумму и проверить наличие
                total = Decimal('0.00')
                order_items = []
                
                for slug, item in cart.items():
                    product = Product.objects.get(slug=slug, is_active=True)
                    quantity = item['quantity']
                    
                    if product.stock < quantity:
                        raise ValueError(
                            f'Недостаточно товара "{product.name}" на складе'
                        )
                    
                    price = product.price
                    subtotal = price * quantity
                    total += subtotal
                    
                    order_items.append({
                        'product': product,
                        'quantity': quantity,
                        'price': price,
                    })
                
                # Создать заказ
                order = Order.objects.create(
                    customer=customer,
                    total_amount=total,
                    delivery_address=form.cleaned_data['address'],
                    notes=form.cleaned_data.get('notes', ''),
                )
                
                # Добавить товары в заказ
                for item_data in order_items:
                    OrderItem.objects.create(
                        order=order,
                        product=item_data['product'],
                        quantity=item_data['quantity'],
                        price=item_data['price'],
                    )
                    
                    # Уменьшить остаток на складе
                    product = item_data['product']
                    product.stock -= item_data['quantity']
                    product.save()
                
                # Очистить корзину
                request.session['cart'] = {}
                request.session.modified = True
                
                messages.success(
                    request,
                    f'Заказ #{order.id} успешно оформлен!'
                )
                return redirect('shop:order_success', pk=order.pk)
                
            except Exception as e:
                messages.error(request, f'Ошибка при создании заказа: {str(e)}')
                return redirect('shop:checkout')
    else:
        form = CheckoutForm()
    
    # Подготовить данные корзины для отображения
    cart_items = []
    total = Decimal('0.00')
    
    for slug, item in cart.items():
        try:
            product = Product.objects.get(slug=slug, is_active=True)
            price = Decimal(item['price'])
            quantity = item['quantity']
            subtotal = price * quantity
            
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'price': price,
                'subtotal': subtotal,
            })
            total += subtotal
        except Product.DoesNotExist:
            pass
    
    context = {
        'form': form,
        'cart_items': cart_items,
        'total': total,
    }
    return render(request, 'shop/checkout.html', context)


def order_success(request, pk):
    """Страница успешного заказа"""
    order = get_object_or_404(
        Order.objects.select_related('customer').prefetch_related('items__product'),
        pk=pk
    )
    
    context = {
        'order': order,
    }
    return render(request, 'shop/order_success.html', context)
