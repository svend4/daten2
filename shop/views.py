# shop/views.py
import json
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Product, Customer, Order, OrderItem, OrderStatusHistory


def index(request):
    """Каталог товаров с необязательным поиском."""
    products = Product.objects.filter(is_active=True).select_related('category')

    search_query = request.GET.get('search', '').strip()
    if search_query:
        products = products.filter(name__icontains=search_query)

    return render(request, 'index.html', {
        'products': products,
        'search_query': search_query,
    })


def create_order(request, product_id):
    """Быстрый заказ одного товара по имени и телефону."""
    product = get_object_or_404(Product, id=product_id, is_active=True)

    if request.method != 'POST':
        return redirect('index')

    name = (request.POST.get('name') or '').strip()
    phone = (request.POST.get('phone') or '').strip()

    if not name:
        messages.error(request, 'Укажите имя')
        return redirect('index')

    if product.stock < 1:
        messages.error(request, f'Товар «{product.name}» закончился')
        return redirect('index')

    try:
        line_total = Decimal(product.price)
        customer = Customer.objects.create(name=name, phone=phone)
        order = Order.objects.create(
            customer=customer,
            subtotal=line_total,
            total_amount=line_total,
            payment_status='pending',
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            quantity=1,
            unit_price=product.price,
            line_total=line_total,
        )
        OrderStatusHistory.objects.create(order=order, status='new', note='Заказ создан')
        product.stock -= 1
        product.save()

        messages.success(
            request,
            f'Заказ на «{product.name}» оформлен! Номер для отслеживания: {order.order_number}'
        )
    except Exception:
        messages.error(request, 'Не удалось оформить заказ. Попробуйте позже.')

    return redirect('index')


# ============= ЕДИНЫЙ JSON API (канонический контракт) =============

def api_health(request):
    return JsonResponse({'ok': True, 'level': 3, 'stack': 'Django'})


def api_products(request):
    products = (Product.objects.filter(is_active=True)
                .select_related('category').order_by('-is_featured', 'name'))
    data = [{
        'id': p.id, 'name': p.name, 'slug': p.slug, 'description': p.description,
        'price': float(p.price), 'currency': p.currency, 'image': p.image, 'sku': p.sku,
        'stock': p.stock, 'is_featured': p.is_featured,
        'category_name': p.category.name if p.category else None,
    } for p in products]
    return JsonResponse(data, safe=False)


@csrf_exempt
def api_create_order(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)
    try:
        data = json.loads(request.body or b'{}')
    except Exception:
        data = {}
    name = (data.get('name') or '').strip()
    items = data.get('items') or []
    if not name or not items:
        return JsonResponse({'error': 'name/items required'}, status=400)
    try:
        priced = []
        subtotal = Decimal('0')
        for it in items:
            pid = int(it.get('product_id') or 0)
            qty = int(it.get('quantity') or it.get('qty') or 1)
            if qty < 1:
                continue
            prod = Product.objects.filter(id=pid, is_active=True).first()
            if not prod:
                continue
            line = prod.price * qty
            subtotal += line
            priced.append((prod, qty, line))
        if not priced:
            return JsonResponse({'error': 'no valid items'}, status=400)

        customer = Customer.objects.create(
            name=name, phone=(data.get('phone') or ''),
            email=(data.get('email') or ''), address=(data.get('address') or ''))
        order = Order.objects.create(
            customer=customer, subtotal=subtotal, total_amount=subtotal,
            payment_status='pending', delivery_address=(data.get('address') or ''))
        for prod, qty, line in priced:
            OrderItem.objects.create(
                order=order, product=prod, product_name=prod.name,
                quantity=qty, unit_price=prod.price, line_total=line)
            prod.stock -= qty
            prod.save()
        OrderStatusHistory.objects.create(order=order, status='new', note='Заказ создан')
        return JsonResponse({'order_number': order.order_number, 'total': float(subtotal)}, status=201)
    except Exception:
        return JsonResponse({'error': 'order failed'}, status=400)


def api_get_order(request, order_number):
    order = (Order.objects.filter(order_number=order_number)
             .select_related('customer').prefetch_related('items').first())
    if not order:
        return JsonResponse({'error': 'not found'}, status=404)
    return JsonResponse({
        'order': {
            'order_number': order.order_number, 'status': order.status,
            'payment_status': order.payment_status, 'total_amount': float(order.total_amount),
            'customer_name': order.customer.name, 'phone': order.customer.phone,
        },
        'items': [{
            'product_name': i.product_name, 'quantity': i.quantity,
            'unit_price': float(i.unit_price), 'line_total': float(i.line_total),
        } for i in order.items.all()],
    })
