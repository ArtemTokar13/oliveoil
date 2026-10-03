import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import DiscountCode, Order, OrderItem, ShippingSettings

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


def find_discount_code(raw_code, email=None):
    """Return (DiscountCode, None) if usable, else (None, error message).
    `email` is checked when known — at the final checkout submit it always is."""
    raw_code = (raw_code or "").strip().upper()
    if not raw_code:
        return None, "Introduce un código de descuento."
    discount_code = DiscountCode.objects.filter(code=raw_code).first()
    if discount_code is None:
        return None, "Este código de descuento no existe."
    if discount_code.is_used:
        return None, "Este código de descuento ya se ha utilizado."
    if discount_code.is_expired:
        return None, "Este código de descuento ha caducado."
    if email is not None and discount_code.email != email.strip().lower():
        return None, "Este código pertenece a otro cliente: solo es válido con el correo al que se envió."
    return discount_code, None


def create_order(request, shipping_fields, email, discount_code=None):
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
    postal_code = shipping_fields["postal_code"]
    # Free-shipping threshold is judged on the pre-discount subtotal, so a
    # loyalty code never costs the customer their free shipping.
    shipping_cost = shipping_settings.shipping_cost_for(subtotal, postal_code=postal_code)
    is_local_delivery = shipping_settings.is_local_delivery_postal_code(postal_code)
    local_delivery_date = shipping_settings.next_local_delivery_date() if is_local_delivery else None
    discount_amount = discount_code.discount_for(subtotal) if discount_code else Decimal("0")
    total = subtotal - discount_amount + shipping_cost

    order = Order.objects.create(
        user=request.user if request.user.is_authenticated else None,
        email=email,
        session_key=request.session.session_key or "",
        shipping_full_name=shipping_fields["full_name"],
        shipping_phone=shipping_fields["phone"],
        shipping_street_address=shipping_fields["street_address"],
        shipping_apartment=shipping_fields.get("apartment", ""),
        shipping_postal_code=postal_code,
        shipping_city=shipping_fields["city"],
        shipping_province=shipping_fields["province"],
        subtotal=subtotal,
        discount_code=discount_code,
        discount_amount=discount_amount,
        shipping_cost=shipping_cost,
        total=total,
        is_local_delivery=is_local_delivery,
        local_delivery_date=local_delivery_date,
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

    extra = {}
    if order.discount_amount:
        # A one-off fixed-amount coupon for exactly the discount we computed,
        # so Stripe's total always matches order.total to the cent.
        coupon = stripe.Coupon.create(
            amount_off=int(order.discount_amount * 100),
            currency="eur",
            duration="once",
            max_redemptions=1,
            name=f"Descuento {order.discount_code.code}" if order.discount_code else "Descuento",
        )
        extra["discounts"] = [{"coupon": coupon.id}]

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=line_items,
        customer_email=order.email or None,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"order_id": str(order.pk)},
        **extra,
    )
    order.stripe_checkout_session_id = session.id
    order.save(update_fields=["stripe_checkout_session_id"])
    return session


def issue_loyalty_code(order):
    """Give a paid order's customer a code for their next purchase. Idempotent
    per order, so a retried webhook never hands out a second one."""
    if not order.email:
        return None
    existing = order.issued_discount_codes.first()
    if existing:
        return existing
    return DiscountCode.objects.create(
        email=order.email,
        percent=Decimal(settings.LOYALTY_DISCOUNT_PERCENT),
        issued_for_order=order,
    )


def mark_discount_code_used(order):
    if order.discount_code_id:
        DiscountCode.objects.filter(pk=order.discount_code_id, used_at__isnull=True).update(used_at=timezone.now())


def send_order_confirmation_email(request, order, loyalty_code=None):
    """Best-effort — a delivery failure here shouldn't turn a successful
    payment into a 500 for the Stripe webhook (Stripe would just retry it)."""
    if not order.email:
        return
    status_url = request.build_absolute_uri(order.get_status_url())
    body = render_to_string("orders/order_confirmation_email.txt", {
        "order": order, "status_url": status_url, "SITE_NAME": settings.SITE_NAME,
        "loyalty_code": loyalty_code,
    })
    try:
        EmailMessage(
            subject=f"Confirmación de tu pedido #{order.order_number} — {settings.SITE_NAME}",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[order.email],
            # Sent from no-reply — a customer hitting "Reply" should reach us.
            reply_to=[settings.CONTACT_EMAIL],
        ).send()
    except Exception:
        logger.exception("No se ha podido enviar el correo de confirmación del pedido #%s", order.pk)


def send_new_order_notification(request, order):
    """Tell the shop owner a paid order came in. Best-effort, same as the
    customer confirmation — never fail the Stripe webhook over it."""
    recipients = settings.ORDER_NOTIFICATION_EMAILS
    if not recipients:
        return
    admin_url = request.build_absolute_uri(reverse("admin:orders_order_change", args=[order.pk]))
    body = render_to_string("orders/order_notification_email.txt", {
        "order": order, "admin_url": admin_url,
    })
    try:
        EmailMessage(
            subject=f"Nuevo pedido #{order.order_number} — {order.total} € — {order.shipping_full_name}",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
            reply_to=[order.email] if order.email else None,
        ).send()
    except Exception:
        logger.exception("No se ha podido enviar el aviso de nuevo pedido #%s", order.pk)


# Statuses the customer hears about — RECEIVED is the starting state and
# is already covered by the order confirmation email.
STATUS_EMAIL_SUBJECTS = {
    Order.FulfillmentStatus.PROCESSING: "Estamos preparando tu pedido #{number}",
    Order.FulfillmentStatus.SHIPPED: "Tu pedido #{number} está en camino",
    Order.FulfillmentStatus.DELIVERED: "Tu pedido #{number} ha sido entregado",
}


def send_status_update_email(request, order):
    """Tell the customer their paid order moved to a new shipping state.
    Returns True if an email went out. Best-effort: logs and returns False on
    failure so an admin save never breaks over email delivery."""
    subject_template = STATUS_EMAIL_SUBJECTS.get(order.fulfillment_status)
    if not subject_template or order.status != Order.Status.PAID or not order.email:
        return False
    loyalty_code = order.issued_discount_codes.filter(
        used_at__isnull=True, expires_at__gt=timezone.now(),
    ).first()
    body = render_to_string("orders/order_status_email.txt", {
        "order": order,
        "status_url": request.build_absolute_uri(order.get_status_url()),
        "loyalty_code": loyalty_code,
        "SITE_NAME": settings.SITE_NAME,
    })
    try:
        EmailMessage(
            subject=f"{subject_template.format(number=order.order_number)} — {settings.SITE_NAME}",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[order.email],
            reply_to=[settings.CONTACT_EMAIL],
        ).send()
    except Exception:
        logger.exception("No se ha podido enviar el correo de cambio de estado del pedido #%s", order.pk)
        return False
    return True
