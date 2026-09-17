from django.conf import settings
from django.db import models

from catalog.models import Product


class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="usuario",
        on_delete=models.CASCADE, null=True, blank=True, related_name="cart",
    )
    session_key = models.CharField(max_length=40, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "carrito"
        verbose_name_plural = "carritos"

    def __str__(self):
        return f"Carrito de {self.user}" if self.user else f"Carrito anónimo {self.session_key}"

    @property
    def items_count(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.items.all()), start=0)


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "artículo del carrito"
        verbose_name_plural = "artículos del carrito"
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="unique_cart_product"),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    @property
    def line_total(self):
        return self.product.price * self.quantity
