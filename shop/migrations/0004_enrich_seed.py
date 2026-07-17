from django.db import migrations


def enrich(apps, schema_editor):
    Product = apps.get_model('shop', 'Product')
    meta = {
        'red-rose':     ('ROSE-RED-01', True),
        'yellow-tulip': ('TULIP-YEL-01', False),
        'peony':        ('PEONY-01', True),
    }
    for slug, (sku, featured) in meta.items():
        Product.objects.filter(slug=slug).update(sku=sku, is_featured=featured, currency='EUR')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0003_cart_alter_product_options_remove_orderitem_price_and_more'),
    ]

    operations = [
        migrations.RunPython(enrich, noop),
    ]
