from django.contrib import admin
from django.urls import path
from shop import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.index, name='index'),
    path('order/<int:product_id>/', views.create_order, name='create_order'),

    # Единый JSON API (канонический контракт)
    path('api/health', views.api_health),
    path('api/products', views.api_products),
    path('api/orders', views.api_create_order),
    path('api/orders/<str:order_number>', views.api_get_order),
]
