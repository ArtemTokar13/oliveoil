import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import Address
from accounts.utils import address_fields_from_post, address_to_dict, validate_address
from catalog.models import Product

from .models import Order, ShippingSettings
from .services import (
    CheckoutError,
    build_line_items,
    create_order,
    create_stripe_checkout_session,
    send_order_confirmation_email,
)


@require_POST
def buy_now(request):
    # Deliberately not @login_required: it POSTs, and Django's post-login
    # redirect is always a GET, which would 405 against a POST-only view.
    # The session-stored intent survives login (session key is cycled, not
    # flushed), so checkout — a GET-friendly, login_required view — is what
    # actually sends anonymous users to the login page.
    product = get_object_or_404(Product, pk=request.POST.get("product_id"), is_active=True)
    try:
        quantity = max(1, int(request.POST.get("quantity", 1)))
    except (TypeError, ValueError):
        quantity = 1
    request.session["buy_now"] = {"product_id": product.pk, "quantity": quantity}
    return redirect("orders:checkout")


def checkout(request):
    # No @login_required — purchasing must never force an account. Guests
    # type a one-off shipping address + email; the email is what the order
    # status link gets sent to, since there's no account to log into later.
    line_items = build_line_items(request)
    if not line_items:
        messages.info(request, "Tu carrito está vacío.")
        return redirect("cart:detail")

    is_guest = not request.user.is_authenticated
    addresses = request.user.addresses.all() if not is_guest else Address.objects.none()
    new_address_errors = {}
    new_address_values = {}
    guest_email = ""
    guest_email_error = None

    if request.method == "POST":
        shipping_fields = None
        email = None

        if is_guest:
            guest_email = request.POST.get("email", "").strip().lower()
            new_address_values = address_fields_from_post(request.POST)
            new_address_errors = validate_address(new_address_values)
            try:
                validate_email(guest_email)
            except ValidationError:
                guest_email_error = "Introduce un correo electrónico válido."

            if not guest_email_error and not new_address_errors:
                shipping_fields = new_address_values
                email = guest_email
        else:
            address_id = request.POST.get("address_id")
            if address_id == "new":
                new_address_values = address_fields_from_post(request.POST)
                new_address_errors = validate_address(new_address_values)
                if not new_address_errors:
                    address = Address.objects.create(user=request.user, **new_address_values)
                    shipping_fields = address_to_dict(address)
            elif address_id:
                address = get_object_or_404(Address, pk=address_id, user=request.user)
                shipping_fields = address_to_dict(address)
            else:
                messages.error(request, "Selecciona o añade una dirección de envío.")
            email = request.user.email

        if shipping_fields:
            try:
                with transaction.atomic():
                    order = create_order(request, shipping_fields, email=email)
                    session = create_stripe_checkout_session(request, order)
            except CheckoutError as exc:
                messages.error(request, str(exc))
            except stripe.error.StripeError:
                messages.error(request, "No se ha podido conectar con la pasarela de pago. Inténtalo de nuevo en unos minutos.")
            else:
                request.session.pop("buy_now", None)
                return redirect(session.url)

    subtotal = sum((product.price * quantity for product, quantity in line_items), start=0)
    shipping_settings = ShippingSettings.get_solo()
    shipping_cost = shipping_settings.shipping_cost_for(subtotal)

    return render(request, "orders/checkout.html", {
        "addresses": addresses,
        "line_items": line_items,
        "subtotal": subtotal,
        "shipping_cost": shipping_cost,
        "total": subtotal + shipping_cost,
        "new_address_errors": new_address_errors,
        "new_address_values": new_address_values,
        "is_guest": is_guest,
        "guest_email": guest_email,
        "guest_email_error": guest_email_error,
    })


def checkout_cancel(request):
    token = request.GET.get("token")
    if token:
        Order.objects.filter(access_token=token, status=Order.Status.PENDING).update(
            status=Order.Status.CANCELLED
        )
    return render(request, "orders/checkout_cancel.html")


def order_status(request, token):
    # Token-based, not login_required — this is the link emailed after
    # payment, and it's the only way a guest (no account) can ever see
    # their order again, so it has to work without being signed in.
    order = get_object_or_404(Order, access_token=token)
    return render(request, "orders/confirmation.html", {"order": order})


@login_required
def order_list(request):
    orders = request.user.orders.exclude(status=Order.Status.PENDING)
    return render(request, "orders/order_list.html", {"orders": orders})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk, user=request.user)
    return render(request, "orders/order_detail.html", {"order": order})


@csrf_exempt
def stripe_webhook(request):
    if request.method != "POST":
        return HttpResponseBadRequest()

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponseBadRequest()

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        order_id = (session.get("metadata") or {}).get("order_id")

        order = None
        if order_id:
            order = Order.objects.filter(pk=order_id).first()
        if order is None:
            order = Order.objects.filter(stripe_checkout_session_id=session.get("id")).first()

        if order and order.status != Order.Status.PAID:
            with transaction.atomic():
                order.status = Order.Status.PAID
                order.paid_at = timezone.now()
                order.stripe_payment_intent_id = session.get("payment_intent", "")
                order.save(update_fields=["status", "paid_at", "stripe_payment_intent_id", "updated_at"])

                for item in order.items.all():
                    Product.objects.filter(pk=item.product_id).update(
                        stock=Greatest(F("stock") - item.quantity, 0)
                    )

                # A webhook call carries no session cookie, so for guest
                # orders (no user) the only way back to "their" cart is the
                # session_key captured at checkout time.
                from cart.models import Cart
                if order.user_id:
                    cart_lookup = {"user_id": order.user_id}
                elif order.session_key:
                    cart_lookup = {"session_key": order.session_key}
                else:
                    cart_lookup = None
                if cart_lookup:
                    cart = Cart.objects.filter(**cart_lookup).first()
                    if cart:
                        cart.items.all().delete()

            send_order_confirmation_email(request, order)

    return HttpResponse(status=200)
