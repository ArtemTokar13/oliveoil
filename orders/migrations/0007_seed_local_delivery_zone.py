from django.db import migrations


LOCAL_DELIVERY_POSTAL_CODES = (
    "12001,12002,12003,12004,12005,12006,12100,12071,"  # Castellón de la Plana + el Grao
    "12529,12530,"  # Burriana
    "12540,"  # Vila-real
    "12550,"  # Almassora
    "12560"   # Benicàssim
)

# Friday by default — adjustable any time from the admin without a migration.
LOCAL_DELIVERY_WEEKDAY = 4


def seed_local_delivery_zone(apps, schema_editor):
    ShippingSettings = apps.get_model("orders", "ShippingSettings")
    settings_obj, _ = ShippingSettings.objects.get_or_create(pk=1)
    if not settings_obj.local_delivery_postal_codes:
        settings_obj.local_delivery_postal_codes = LOCAL_DELIVERY_POSTAL_CODES
        settings_obj.local_delivery_weekday = LOCAL_DELIVERY_WEEKDAY
        settings_obj.save(update_fields=["local_delivery_postal_codes", "local_delivery_weekday"])


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0006_order_is_local_delivery_order_local_delivery_date_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_local_delivery_zone, migrations.RunPython.noop),
    ]
