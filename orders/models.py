import secrets
import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product


class ShippingSettings(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Lunes"
        TUESDAY = 1, "Martes"
        WEDNESDAY = 2, "Miércoles"
        THURSDAY = 3, "Jueves"
        FRIDAY = 4, "Viernes"
        SATURDAY = 5, "Sábado"
        SUNDAY = 6, "Domingo"

    flat_fee = models.DecimalField("gastos de envío (€)", max_digits=6, decimal_places=2, default=Decimal("4.95"))
    free_shipping_threshold = models.DecimalField(
        "envío gratis a partir de (€)", max_digits=8, decimal_places=2,
        null=True, blank=True,
        help_text="Deja en blanco para no ofrecer envío gratuito.",
    )
    local_delivery_postal_codes = models.CharField(
        "códigos postales de reparto local gratuito", max_length=500, blank=True,
        help_text=(
            "Códigos postales con envío gratuito y reparto semanal propio, separados por "
            "comas (p. ej. 12001,12002,12003,12004,12005,12006,12100,12530,12540,12550,12560 "
            "para Castellón de la Plana, el Grao, Burriana, Vila-real, Almassora y Benicàssim). "
            "Deja en blanco para desactivar el reparto local."
        ),
    )
    local_delivery_weekday = models.PositiveSmallIntegerField(
        "día de reparto local", choices=Weekday.choices,
        null=True, blank=True,
        help_text="Día de la semana en que se realiza el reparto local. Requiere haber indicado códigos postales.",
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

    def local_delivery_postal_code_list(self):
        return [code.strip() for code in self.local_delivery_postal_codes.split(",") if code.strip()]

    def is_local_delivery_postal_code(self, postal_code):
        if not postal_code or self.local_delivery_weekday is None:
            return False
        return postal_code.strip() in self.local_delivery_postal_code_list()

    def shipping_cost_for(self, subtotal, postal_code=None):
        if self.is_local_delivery_postal_code(postal_code):
            return 0
        if self.free_shipping_threshold is not None and subtotal >= self.free_shipping_threshold:
            return 0
        return self.flat_fee

    def next_local_delivery_date(self, from_date=None):
        """Next occurrence of the weekly local round, strictly after `from_date`
        (today by default) so there's always at least a day to prepare the order."""
        if self.local_delivery_weekday is None:
            return None
        from_date = from_date or timezone.localdate()
        days_ahead = (self.local_delivery_weekday - from_date.weekday()) % 7 or 7
        return from_date + timedelta(days=days_ahead)


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente de pago"
        PAID = "PAID", "Pagado"
        CANCELLED = "CANCELLED", "Cancelado"

    class FulfillmentStatus(models.TextChoices):
        RECEIVED = "RECEIVED", "Recibido"
        PROCESSING = "PROCESSING", "En preparación"
        SHIPPED = "SHIPPED", "Enviado"
        DELIVERED = "DELIVERED", "Entregado"

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
    # Only meaningful once status == PAID — tracked separately from payment
    # status because a paid order still moves through its own shipping states.
    fulfillment_status = models.CharField(
        "estado de envío", max_length=20,
        choices=FulfillmentStatus.choices, default=FulfillmentStatus.RECEIVED,
    )

    shipping_full_name = models.CharField("nombre completo", max_length=150)
    shipping_phone = models.CharField("teléfono", max_length=30)
    shipping_street_address = models.CharField("dirección", max_length=200)
    shipping_apartment = models.CharField("piso / puerta", max_length=100, blank=True)
    shipping_postal_code = models.CharField("código postal", max_length=10)
    shipping_city = models.CharField("ciudad", max_length=100)
    shipping_province = models.CharField("provincia", max_length=100)
    shipping_country = models.CharField("país", max_length=100, default="España")

    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    discount_code = models.ForeignKey(
        "DiscountCode", verbose_name="código de descuento", related_name="orders",
        on_delete=models.SET_NULL, null=True, blank=True,
    )
    discount_amount = models.DecimalField("descuento", max_digits=8, decimal_places=2, default=Decimal("0"))
    shipping_cost = models.DecimalField(max_digits=8, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    tracking_number = models.CharField(
        "número de seguimiento", max_length=100, blank=True,
        help_text="Se incluye en el correo al cliente cuando el pedido pasa a «Enviado».",
    )
    tracking_url = models.URLField(
        "enlace de seguimiento", blank=True,
        help_text="Enlace a la web del transportista para seguir el envío (opcional).",
    )

    # Snapshotted at order creation (not recomputed from ShippingSettings on
    # every view) so the date shown to the customer never drifts as weeks pass.
    is_local_delivery = models.BooleanField("reparto local", default=False)
    local_delivery_date = models.DateField("fecha de reparto local", null=True, blank=True)

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
        return f"Pedido #{self.order_number} — {self.user or self.email}"

    @property
    def order_number(self):
        """Human-facing order number — derived from access_token (random per
        order), not pk, so customers can't infer how many orders exist."""
        return f"{self.access_token.hex[:5].upper()}"

    @property
    def display_status(self):
        """What the customer sees as 'the' status — payment status while
        unpaid/cancelled, fulfillment progress once it's actually paid."""
        if self.status == self.Status.PAID:
            return self.get_fulfillment_status_display()
        return self.get_status_display()

    @property
    def display_status_css(self):
        if self.status == self.Status.CANCELLED:
            return "border-ink-muted text-ink-muted"
        if self.status == self.Status.PAID and self.fulfillment_status == self.FulfillmentStatus.DELIVERED:
            return "border-accent-2 text-accent-2"
        return "border-accent text-accent"

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


def _generate_discount_code():
    # No 0/O, 1/I/L — codes get read off a phone and typed by hand.
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    while True:
        code = "OLIV-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not DiscountCode.objects.filter(code=code).exists():
            return code


def _default_discount_expiry():
    return timezone.now() + timedelta(days=settings.LOYALTY_DISCOUNT_VALID_DAYS)


class DiscountCode(models.Model):
    """Single-use, percentage-off-products code tied to one customer email.
    Issued automatically after every paid order ("X % en tu próxima compra")
    and can also be created by hand in the admin."""

    code = models.CharField("código", max_length=20, unique=True, blank=True,
                            help_text="Déjalo en blanco para generarlo automáticamente.")
    email = models.EmailField("correo del cliente", help_text="Solo se puede usar en pedidos con este correo.")
    percent = models.DecimalField("descuento (%)", max_digits=5, decimal_places=2,
                                  default=Decimal("5"))
    expires_at = models.DateTimeField("válido hasta", default=_default_discount_expiry)
    issued_for_order = models.ForeignKey(
        Order, verbose_name="emitido por el pedido", related_name="issued_discount_codes",
        on_delete=models.SET_NULL, null=True, blank=True,
    )
    used_at = models.DateTimeField("usado el", null=True, blank=True)
    created_at = models.DateTimeField("creado el", auto_now_add=True)

    class Meta:
        verbose_name = "código de descuento"
        verbose_name_plural = "códigos de descuento"
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        if not self.code:
            self.code = _generate_discount_code()
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    @property
    def is_used(self):
        return self.used_at is not None

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_active(self):
        return not self.is_used and not self.is_expired

    def discount_for(self, subtotal):
        return (Decimal(subtotal) * self.percent / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Customer(Order):
    """Admin-only stand-in so "Clientes" shows up in the admin sidebar —
    its changelist is a custom aggregated view (see CustomerAdmin), since a
    customer isn't a table: guests only exist as an email on their orders."""

    class Meta:
        proxy = True
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
