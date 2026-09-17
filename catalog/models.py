from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Brand(models.Model):
    name = models.CharField("nombre", max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    story = models.TextField("historia", blank=True)
    logo = models.ImageField("logotipo", upload_to="marcas/", blank=True, null=True)

    class Meta:
        verbose_name = "marca"
        verbose_name_plural = "marcas"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Category(models.Model):
    name = models.CharField("nombre", max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.TextField("descripción", blank=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Product(models.Model):
    class Volume(models.TextChoices):
        ML250 = "250ML", "250 ml"
        ML500 = "500ML", "500 ml"
        ML750 = "750ML", "750 ml"
        L1 = "1L", "1 L"
        L2 = "2L", "2 L"
        L3 = "3L", "3 L"
        L5 = "5L", "5 L"

    name = models.CharField("nombre", max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    brand = models.ForeignKey(
        Brand, verbose_name="marca", related_name="products",
        on_delete=models.SET_NULL, null=True, blank=True,
    )
    category = models.ForeignKey(
        Category, verbose_name="categoría", related_name="products",
        on_delete=models.PROTECT,
    )
    volume = models.CharField("volumen", max_length=10, choices=Volume.choices)
    origin_region = models.CharField("origen / región", max_length=120, blank=True)
    harvest_year = models.PositiveSmallIntegerField("cosecha", blank=True, null=True)
    acidity = models.DecimalField(
        "acidez (%)", max_digits=4, decimal_places=2, blank=True, null=True,
    )
    price = models.DecimalField("precio (€)", max_digits=8, decimal_places=2)
    stock = models.PositiveIntegerField("stock", default=0)
    description = models.TextField("descripción", blank=True)
    is_active = models.BooleanField("activo", default=True, help_text="Desmarca para ocultar el producto de la tienda sin borrarlo.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_volume_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(f"{self.name}-{self.get_volume_display()}")
            slug = base_slug
            i = 2
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product_detail", kwargs={"slug": self.slug})

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def main_image(self):
        return self.images.first()


class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name="images", on_delete=models.CASCADE)
    image = models.ImageField("imagen", upload_to="productos/")
    alt_text = models.CharField("texto alternativo", max_length=200, blank=True)
    order = models.PositiveSmallIntegerField("orden", default=0)

    class Meta:
        verbose_name = "imagen de producto"
        verbose_name_plural = "imágenes de producto"
        ordering = ["order", "id"]

    def __str__(self):
        return self.alt_text or f"Imagen de {self.product.name}"
