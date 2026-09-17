import io
import random

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw

from catalog.models import Brand, Category, Product, ProductImage

PALETTE = ["#96730E", "#55643A", "#6E6B54", "#232014", "#8CA35D", "#DDAC30"]

BRANDS = [
    ("Cortijo del Sur", "Cooperativa familiar en Jaén con más de tres generaciones prensando aceituna picual."),
    ("Finca Almazara", "Producción limitada en Córdoba, especializada en aceites ecológicos de baja acidez."),
    ("Molino Sierra Mágina", "Cooperativa de la sierra de Jaén, referente en denominación de origen."),
    ("Verde Oliva", "Pequeño productor catalán centrado en variedades arbequina."),
]

CATEGORIES = ["Virgen Extra", "Virgen", "Ecológico"]

VOLUMES = [c[0] for c in Product.Volume.choices]

REGIONS = ["Jaén, Andalucía", "Córdoba, Andalucía", "Tarragona, Cataluña", "Toledo, Castilla-La Mancha"]

PRODUCT_NAMES = [
    "Selección Picual", "Reserva Familiar", "Cosecha Temprana", "Coupage Clásico",
    "Arbequina Suave", "Gran Reserva", "Ecológico Certificado", "Edición Limitada",
]


def make_placeholder_image(text, color):
    img = Image.new("RGB", (800, 1000), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 760, 960], outline="#F1EEDD", width=3)
    words = text.split()
    lines, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) > 16:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    y = 460
    for line in lines:
        draw.text((80, y), line, fill="#F1EEDD")
        y += 30
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return ContentFile(buffer.getvalue(), name=f"{text.lower().replace(' ', '-')}.jpg")


class Command(BaseCommand):
    help = "Seed the catalog with sample brands, categories and products for local development."

    def handle(self, *args, **options):
        categories = {}
        for name in CATEGORIES:
            category, _ = Category.objects.get_or_create(name=name)
            categories[name] = category

        brands = []
        for name, story in BRANDS:
            brand, _ = Brand.objects.get_or_create(name=name, defaults={"story": story})
            brands.append(brand)

        created = 0
        for i, product_name in enumerate(PRODUCT_NAMES):
            brand = brands[i % len(brands)]
            category = categories[CATEGORIES[i % len(CATEGORIES)]]
            volume = VOLUMES[i % len(VOLUMES)]
            full_name = f"{brand.name} {product_name}"

            product, was_created = Product.objects.get_or_create(
                name=full_name,
                volume=volume,
                defaults={
                    "brand": brand,
                    "category": category,
                    "origin_region": REGIONS[i % len(REGIONS)],
                    "harvest_year": 2023 + (i % 3),
                    "acidity": round(0.2 + (i % 5) * 0.08, 2),
                    "price": round(6.5 + i * 1.35, 2),
                    "stock": 40 if i % 5 else 0,
                    "description": (
                        f"{full_name} es un aceite de oliva {category.name.lower()} producido en "
                        f"{REGIONS[i % len(REGIONS)]}. Cosecha {2023 + (i % 3)}, envasado en origen "
                        "para conservar todo su aroma y propiedades."
                    ),
                },
            )
            if was_created:
                created += 1
                image_file = make_placeholder_image(full_name, PALETTE[i % len(PALETTE)])
                ProductImage.objects.create(product=product, image=image_file, alt_text=full_name, order=0)

        self.stdout.write(self.style.SUCCESS(f"Catálogo listo: {created} productos nuevos creados."))
