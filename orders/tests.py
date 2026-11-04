from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from catalog.models import Category, Product

from .models import Order, ShippingSettings

LOCAL_POSTAL_CODES = {
    "12001": "Castellón de la Plana",
    "12100": "El Grao",
    "12530": "Burriana",
    "12540": "Vila-real",
    "12550": "Almassora",
    "12560": "Benicàssim",
}


class CheckoutShippingTests(TestCase):
    """Full guest checkout up to the Stripe call, reading what Stripe would charge."""

    @classmethod
    def setUpTestData(cls):
        ShippingSettings.objects.filter(pk=1).update(
            flat_fee=Decimal("5.00"), free_shipping_threshold=Decimal("40.00"),
            local_delivery_postal_codes=",".join(LOCAL_POSTAL_CODES), local_delivery_weekday=4,
        )
        category = Category.objects.create(name="AOVE")
        cls.product = Product.objects.create(
            name="Picual", category=category, volume=Product.Volume.L1,
            price=Decimal("10.00"), stock=50,
        )

    def checkout(self, postal_code, quantity=1):
        self.client.post(reverse("cart:add"), {"product_id": self.product.pk, "quantity": quantity})
        session = SimpleNamespace(id=f"cs_test_{postal_code}", url="https://stripe.test/pay")
        with patch("orders.services.stripe.checkout.Session.create", return_value=session) as create:
            response = self.client.post(reverse("orders:checkout"), {
                "email": "ana@example.com", "full_name": "Ana Prueba", "phone": "600000000",
                "street_address": "Calle Mayor 1", "postal_code": postal_code,
                "city": "Ciudad", "province": "Provincia",
            })
        self.assertEqual(response.status_code, 302)
        names = [line["price_data"]["product_data"]["name"] for line in create.call_args.kwargs["line_items"]]
        return Order.objects.latest("pk"), names

    def test_local_postal_codes_pay_no_shipping(self):
        for postal_code, city in LOCAL_POSTAL_CODES.items():
            with self.subTest(city=city):
                order, stripe_lines = self.checkout(postal_code)
                self.assertEqual(order.shipping_cost, 0)
                self.assertEqual(order.total, order.subtotal)
                self.assertTrue(order.is_local_delivery)
                self.assertNotIn("Gastos de envío", stripe_lines)

    def test_rest_of_spain_pays_the_flat_fee(self):
        order, stripe_lines = self.checkout("28001")
        self.assertEqual(order.shipping_cost, Decimal("5.00"))
        self.assertEqual(order.total, order.subtotal + Decimal("5.00"))
        self.assertFalse(order.is_local_delivery)
        self.assertIn("Gastos de envío", stripe_lines)

    def test_rest_of_spain_ships_free_from_the_threshold(self):
        order, stripe_lines = self.checkout("28001", quantity=4)
        self.assertEqual(order.subtotal, Decimal("40.00"))
        self.assertEqual(order.shipping_cost, 0)
        self.assertNotIn("Gastos de envío", stripe_lines)


class ShippingBarTests(TestCase):
    TEXT = (
        "Entrega gratis en Castellón y alrededores cada viernes</span><span class=\"hidden sm:inline\"> · </span>"
        "<span class=\"block sm:inline\">Resto de España: 5 € (gratis en pedidos de más de 40 €)"
    )

    def set_shipping(self, **fields):
        ShippingSettings.objects.filter(pk=1).update(**fields)

    def setUp(self):
        self.set_shipping(flat_fee=Decimal("5.00"), free_shipping_threshold=Decimal("40.00"))

    def test_shows_the_configured_terms_on_every_page(self):
        for url in (reverse("catalog:home"), reverse("pages:contact"), reverse("cart:detail")):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), self.TEXT)

    def test_follows_the_settings(self):
        self.set_shipping(flat_fee=Decimal("4.95"), free_shipping_threshold=None, local_delivery_weekday=1)
        response = self.client.get(reverse("catalog:home"))
        self.assertContains(response, "cada martes")
        self.assertContains(response, "Resto de España: 4,95 €")
        self.assertNotContains(response, "gratis en pedidos")

    def test_no_local_promise_when_local_delivery_is_off(self):
        self.set_shipping(local_delivery_weekday=None)
        response = self.client.get(reverse("catalog:home"))
        self.assertNotContains(response, "Entrega gratis en Castellón")
        self.assertContains(response, "Envíos a toda España: 5 €")
