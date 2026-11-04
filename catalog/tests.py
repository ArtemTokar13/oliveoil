from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse

from cart.models import Cart, CartItem
from orders.services import create_order

from .models import Category, Product
from .seo import product_structured_data

SHIPPING_FIELDS = {
    "full_name": "Ana Prueba", "phone": "600000000", "street_address": "Calle Mayor 1",
    "postal_code": "28001", "city": "Madrid", "province": "Madrid",
}


class ProductTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="AOVE")

    def make_product(self, name="Picual", price="10.00", **kwargs):
        return Product.objects.create(
            name=name, category=self.category, volume=Product.Volume.L1,
            price=Decimal(price), stock=5, **kwargs,
        )


class FinalPriceTests(ProductTestCase):
    def test_without_discount_is_the_regular_price(self):
        self.assertEqual(self.make_product().final_price, Decimal("10.00"))

    def test_discount_is_rounded_to_the_cent(self):
        product = self.make_product(price="9.95", discount_percent=15)
        self.assertEqual(product.final_price, Decimal("8.46"))

    def test_cart_line_uses_the_discounted_price(self):
        product = self.make_product(discount_percent=20)
        item = CartItem.objects.create(cart=Cart.objects.create(), product=product, quantity=2)
        self.assertEqual(item.line_total, Decimal("16.00"))

    def test_order_charges_the_discounted_price(self):
        product = self.make_product(discount_percent=20)
        session = self.client.session
        session["buy_now"] = {"product_id": product.pk, "quantity": 2}
        request = RequestFactory().post("/")
        request.session, request.user = session, AnonymousUser()

        order = create_order(request, SHIPPING_FIELDS, email="ana@example.com")

        self.assertEqual(order.subtotal, Decimal("16.00"))
        self.assertEqual(order.items.get().unit_price, Decimal("8.00"))

    def test_structured_data_offers_the_discounted_price(self):
        product = self.make_product(discount_percent=20)
        self.assertEqual(product_structured_data(product)[0]["offers"]["price"], "8.00")


class ShopPageTests(ProductTestCase):
    def test_lower_position_comes_first_then_newest(self):
        older = self.make_product("Antiguo")
        newer = self.make_product("Nuevo")
        pinned = self.make_product("Destacado", position=1)
        response = self.client.get(reverse("catalog:home"))
        self.assertEqual(list(response.context["products"]), [pinned, newer, older])

    def test_card_shows_only_the_discount_banner_when_both_are_set(self):
        self.make_product(discount_percent=15, discount_note="Oferta de lanzamiento", badge_text="Nueva cosecha")
        response = self.client.get(reverse("catalog:home"))
        self.assertContains(response, "−15 %")
        self.assertContains(response, "Oferta de lanzamiento")
        self.assertNotContains(response, "Nueva cosecha")

    def test_card_shows_the_label_when_there_is_no_discount(self):
        self.make_product(badge_text="Nueva cosecha", discount_note="Sin efecto")
        response = self.client.get(reverse("catalog:home"))
        self.assertContains(response, "Nueva cosecha")
        self.assertNotContains(response, "Sin efecto")

    def test_detail_shows_both_banners_and_the_old_price(self):
        product = self.make_product(discount_percent=20, badge_text="Nueva cosecha")
        response = self.client.get(product.get_absolute_url())
        self.assertContains(response, "−20 %")
        self.assertContains(response, "Nueva cosecha")
        self.assertContains(response, "<del")
        self.assertContains(response, "8,00 €")
