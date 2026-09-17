import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse

from catalog.models import Product


class ShippingSettings(models.Model):
    flat_fee = models.DecimalField("gastos de envío (€)", max_digits=6, decimal_places=2, default=Decimal("4.95"))
    free_shipping_threshold = models.DecimalField(
        "envío gratis a partir de (€)", max_digits=8, decimal_places=2,
        null=True, blank=True,
        help_text="Deja en blanco para no ofrecer envío gratuito.",
    )

    class Meta:
        verbose_name = "configuración de envío"
        verbose_name_plural = "configuración de envío"

    def __str__(self):
        return "Configuración de envío"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def shipping_cost_for(self, subtotal):
        if self.free_shipping_threshold is not None and subtotal >= self.free_shipping_threshold:
            return 0
        return self.flat_fee


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente de pago"
        PAID = "PAID", "Pagado"
        CANCELLED = "CANCELLED", "Cancelado"

    # Null for guest checkouts — purchasing never requires an account.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuario",
        related_name="orders", on_delete=models.PROTECT,
        null=True, blank=True,
    )
    # Always set (from the account or typed at guest checkout) — who the
    # order confirmation/status email goes to.
    email = models.EmailField("correo electrónico", blank=True)
    # The anonymous cart's session key at the time of checkout, so the
    # webhook (which has no session/cookies — Stripe calls it server to
    # server) can still find and clear the right guest cart after payment.
    session_key = models.CharField(max_length=40, blank=True)
    # Unguessable id for the "view your order" link emailed after payment —
    # works without login, so it has to not be a sequential pk.
    access_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    shipping_full_name = models.CharField("nombre completo", max_length=150)
    shipping_phone = models.CharField("teléfono", max_length=30)
    shipping_street_address = models.CharField("dirección", max_length=200)
    shipping_apartment = models.CharField("piso / puerta", max_length=100, blank=True)
    shipping_postal_code = models.CharField("código postal", max_length=10)
    shipping_city = models.CharField("ciudad", max_length=100)
    shipping_province = models.CharField("provincia", max_length=100)
    shipping_country = models.CharField("país", max_length=100, default="España")

    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_cost = models.DecimalField(max_digits=8, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pedido #{self.pk} — {self.user or self.email}"

    def get_absolute_url(self):
        """Owner-only view, for the authenticated 'Mis pedidos' list."""
        return reverse("orders:detail", kwargs={"pk": self.pk})

    def get_status_url(self):
        """Token-based view — works for guests and from the emailed link."""
        return reverse("orders:status", kwargs={"token": self.access_token})


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    product_name = models.CharField(max_length=160)
    product_volume = models.CharField(max_length=20)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "artículo del pedido"
        verbose_name_plural = "artículos del pedido"

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity
