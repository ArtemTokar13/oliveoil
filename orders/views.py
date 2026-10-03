from decimal import Decimal

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
    find_discount_code,
    issue_loyalty_code,
    mark_discount_code_used,
    send_new_order_notification,
    send_order_confirmation_email,
)

DISCOUNT_SESSION_KEY = "discount_code"


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
    addresses = list(request.user.addresses.all()) if not is_guest else []
    new_address_errors = {}
    new_address_values = {}
    guest_email = ""
    guest_email_error = None
    discount_error = None
    selected_address_id = None

    # A code applied earlier in this session — dropped quietly if it has
    # since been used or expired (e.g. it was spent on the previous order).
    discount_code = None
    if request.session.get(DISCOUNT_SESSION_KEY):
        discount_code, _ = find_discount_code(request.session[DISCOUNT_SESSION_KEY])
        if discount_code is None:
            request.session.pop(DISCOUNT_SESSION_KEY, None)

    action = request.POST.get("action") if request.method == "POST" else None

    if action in ("apply_discount", "remove_discount"):
        # Re-render with whatever was typed so far, without validating the
        # address — the customer hasn't finished filling it in yet.
        guest_email = request.POST.get("email", "").strip().lower()
        new_address_values = address_fields_from_post(request.POST)
        selected_address_id = request.POST.get("address_id")
        if action == "remove_discount":
            request.session.pop(DISCOUNT_SESSION_KEY, None)
            discount_code = None
        else:
            email = request.user.email if not is_guest else guest_email
            if is_guest and not email:
                discount_error = "Introduce primero tu correo electrónico: el código va asociado a él."
            else:
                found, discount_error = find_discount_code(request.POST.get("discount_code"), email=email)
                if found:
                    discount_code = found
                    request.session[DISCOUNT_SESSION_KEY] = found.code
                    messages.success(request, f"Código {found.code} aplicado: {found.percent.normalize()} % de descuento.")

    elif request.method == "POST":
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

        selected_address_id = request.POST.get("address_id")

        # A code typed in but never "applied" still counts.
        if shipping_fields and not discount_code and request.POST.get("discount_code", "").strip():
            discount_code, discount_error = find_discount_code(request.POST["discount_code"], email=email)
            if discount_error:
                shipping_fields = None
            else:
                request.session[DISCOUNT_SESSION_KEY] = discount_code.code

        # Re-check the applied code against the final email — a guest may
        # have changed the email field after applying it.
        if shipping_fields and discount_code:
            discount_code, discount_error = find_discount_code(discount_code.code, email=email)
            if discount_error:
                request.session.pop(DISCOUNT_SESSION_KEY, None)
                shipping_fields = None

        if shipping_fields:
            try:
                with transaction.atomic():
                    order = create_order(request, shipping_fields, email=email, discount_code=discount_code)
                    session = create_stripe_checkout_session(request, order)
            except CheckoutError as exc:
                messages.error(request, str(exc))
            except stripe.error.StripeError:
                messages.error(request, "No se ha podido conectar con la pasarela de pago. Inténtalo de nuevo en unos minutos.")
            else:
                request.session.pop("buy_now", None)
                return redirect(session.url)

    subtotal = sum((product.price * quantity for product, quantity in line_items), start=Decimal("0"))
    discount_amount = discount_code.discount_for(subtotal) if discount_code else Decimal("0")
    shipping_settings = ShippingSettings.get_solo()
    default_address = next((a for a in addresses if a.is_default), None) or (addresses[0] if addresses else None)
    preview_postal_code = default_address.postal_code if default_address else new_address_values.get("postal_code")
    shipping_cost = shipping_settings.shipping_cost_for(subtotal, postal_code=preview_postal_code)
    local_delivery_postal_codes = shipping_settings.local_delivery_postal_code_list()

    # Only truly "existing" when a saved address is preselected without errors —
    # otherwise the "new address" form is what's shown, so that's the active mode.
    # After a re-render (applying a code), keep whatever the customer had picked.
    if is_guest:
        initial_mode = "new"
    elif selected_address_id and (selected_address_id == "new" or any(str(a.id) == selected_address_id for a in addresses)):
        initial_mode = selected_address_id
    elif new_address_errors or not default_address:
        initial_mode = "new"
    else:
        initial_mode = str(default_address.id)

    return render(request, "orders/checkout.html", {
        "addresses": addresses,
        "line_items": line_items,
        "summary_items": [(product, quantity, product.price * quantity) for product, quantity in line_items],
        "subtotal": subtotal,
        "discount_code": discount_code,
        "discount_amount": discount_amount,
        "discount_error": discount_error,
        "shipping_cost": shipping_cost,
        "total": subtotal - discount_amount + shipping_cost,
        "new_address_errors": new_address_errors,
        "new_address_values": new_address_values,
        "is_guest": is_guest,
        "guest_email": guest_email,
        "guest_email_error": guest_email_error,
        "local_delivery_postal_codes": local_delivery_postal_codes,
        "next_local_delivery_date": shipping_settings.next_local_delivery_date(),
        "checkout_init": {
            "mode": initial_mode,
            "newPostal": new_address_values.get("postal_code", ""),
            "addressPostals": {str(a.id): a.postal_code for a in addresses},
            "zoneCodes": local_delivery_postal_codes,
            "subtotal": float(subtotal),
            "discount": float(discount_amount),
            "flatFee": float(shipping_settings.flat_fee),
            "freeThreshold": (
                float(shipping_settings.free_shipping_threshold)
                if shipping_settings.free_shipping_threshold is not None else None
            ),
        },
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
    loyalty_code = order.issued_discount_codes.filter(used_at__isnull=True).first()
    return render(request, "orders/confirmation.html", {"order": order, "loyalty_code": loyalty_code})


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

                mark_discount_code_used(order)
                loyalty_code = issue_loyalty_code(order)

            send_order_confirmation_email(request, order, loyalty_code=loyalty_code)
            send_new_order_notification(request, order)

    return HttpResponse(status=200)
