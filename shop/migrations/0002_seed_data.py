from django.db import migrations


def seed(apps, schema_editor):
    Category = apps.get_model('shop', 'Category')
    Product = apps.get_model('shop', 'Product')

    categories = {
        'roses': Category.objects.create(name='Розы', slug='roses', description='Классические розы'),
        'tulips': Category.objects.create(name='Тюльпаны', slug='tulips', description='Весенние тюльпаны'),
        'bouquets': Category.objects.create(name='Букеты', slug='bouquets', description='Готовые букеты'),
    }

    products = [
        ('Красная роза', 'red-rose', 'Классическая красная роза премиум класса', '1.50', 'roses', 'images/rose.jpg', 50),
        ('Жёлтый тюльпан', 'yellow-tulip', 'Яркий жёлтый тюльпан', '0.80', 'tulips', 'images/tulip.jpg', 100),
        ('Пион', 'peony', 'Нежный ароматный пион', '2.20', 'bouquets', 'images/peony.jpg', 30),
    ]

    for name, slug, desc, price, cat_key, image, stock in products:
        Product.objects.create(
            name=name, slug=slug, description=desc, price=price,
            category=categories[cat_key], image=image, stock=stock, is_active=True,
        )


def unseed(apps, schema_editor):
    apps.get_model('shop', 'Product').objects.all().delete()
    apps.get_model('shop', 'Category').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
