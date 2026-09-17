import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from .models import Order, OrderItem, ShippingSettings

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


class CheckoutError(Exception):
    pass


def build_line_items(request):
    """Return a list of (product, quantity) for either a 'buy now' item
    held in the session or the visitor's cart."""
    buy_now = request.session.get("buy_now")
    if buy_now:
        from catalog.models import Product
        try:
            product = Product.objects.get(pk=buy_now["product_id"], is_active=True)
        except Product.DoesNotExist:
            return []
        return [(product, buy_now["quantity"])]

    from cart.utils import get_cart
    current_cart = get_cart(request, create=False)
    if not current_cart:
        return []
    return [(item.product, item.quantity) for item in current_cart.items.select_related("product").all()]


def create_order(request, shipping_fields, email):
    """shipping_fields is a plain dict (see accounts.utils.address_fields_from_post
    / address_to_dict) — works the same whether it came from a saved Address
    or was typed fresh at guest checkout, so this doesn't need to know which."""
    line_items = build_line_items(request)
    if not line_items:
        raise CheckoutError("No hay artículos para tramitar.")

    for product, quantity in line_items:
        if quantity > product.stock:
            raise CheckoutError(f"No queda stock suficiente de «{product.name}».")

    subtotal = sum((product.price * quantity for product, quantity in line_items), start=Decimal("0"))
    shipping_settings = ShippingSettings.get_solo()
    shipping_cost = shipping_settings.shipping_cost_for(subtotal)
    total = subtotal + shipping_cost

    order = Order.objects.create(
        user=request.user if request.user.is_authenticated else None,
        email=email,
        session_key=request.session.session_key or "",
        shipping_full_name=shipping_fields["full_name"],
        shipping_phone=shipping_fields["phone"],
        shipping_street_address=shipping_fields["street_address"],
        shipping_apartment=shipping_fields.get("apartment", ""),
        shipping_postal_code=shipping_fields["postal_code"],
        shipping_city=shipping_fields["city"],
        shipping_province=shipping_fields["province"],
        subtotal=subtotal,
        shipping_cost=shipping_cost,
        total=total,
    )
    for product, quantity in line_items:
        OrderItem.objects.create(
            order=order, product=product, product_name=product.name,
            product_volume=product.get_volume_display(), unit_price=product.price,
            quantity=quantity,
        )
    return order


def create_stripe_checkout_session(request, order):
    line_items = [
        {
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f"{item.product_name} ({item.product_volume})"},
                "unit_amount": int(item.unit_price * 100),
            },
            "quantity": item.quantity,
        }
        for item in order.items.all()
    ]
    if order.shipping_cost:
        line_items.append({
            "price_data": {
                "currency": "eur",
                "product_data": {"name": "Gastos de envío"},
                "unit_amount": int(order.shipping_cost * 100),
            },
            "quantity": 1,
        })

    success_url = request.build_absolute_uri(order.get_status_url()) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = request.build_absolute_uri(reverse("orders:checkout_cancel")) + f"?token={order.access_token}"

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=line_items,
        customer_email=order.email or None,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"order_id": str(order.pk)},
    )
    order.stripe_checkout_session_id = session.id
    order.save(update_fields=["stripe_checkout_session_id"])
    return session


def send_order_confirmation_email(request, order):
    """Best-effort — a delivery failure here shouldn't turn a successful
    payment into a 500 for the Stripe webhook (Stripe would just retry it)."""
    if not order.email:
        return
    status_url = request.build_absolute_uri(order.get_status_url())
    body = render_to_string("orders/order_confirmation_email.txt", {
        "order": order, "status_url": status_url, "SITE_NAME": settings.SITE_NAME,
    })
    try:
        send_mail(
            subject=f"Confirmación de tu pedido #{order.pk} — {settings.SITE_NAME}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("No se ha podido enviar el correo de confirmación del pedido #%s", order.pk)
