import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .google_oauth import GoogleOAuthError, build_authorization_url, fetch_userinfo
from .login_codes import send_login_code
from .models import Address, LoginCode
from .utils import address_fields_from_post, address_to_dict, validate_address


def _safe_next_url(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return candidate
    return None


def _get_or_create_user(email, first_name="", last_name=""):
    """Shared by Google sign-in and email-code login: every account is
    created this way, with no usable password — Google or a fresh code is
    the only way in, always."""
    user = User.objects.filter(username=email).first()
    if user is None:
        user = User(username=email, email=email, first_name=first_name[:150], last_name=last_name[:150])
        user.set_unusable_password()
        user.save()
    return user


def _claim_pending_order(request, user):
    """If this login/verification was triggered from a guest order's
    'save my details' button, attach that order to the now-known user and
    save its shipping address — this is the only place that happens, and
    it only runs after the email has just been proven (code or Google)."""
    token = request.session.pop("claim_order_token", None)
    if not token:
        return

    from orders.models import Order
    order = Order.objects.filter(access_token=token, status=Order.Status.PAID, user__isnull=True).first()
    if not order:
        return

    order.user = user
    order.save(update_fields=["user"])

    already_saved = Address.objects.filter(
        user=user, street_address=order.shipping_street_address, postal_code=order.shipping_postal_code,
    ).exists()
    if not already_saved:
        Address.objects.create(
            user=user,
            full_name=order.shipping_full_name, phone=order.shipping_phone,
            street_address=order.shipping_street_address, apartment=order.shipping_apartment,
            postal_code=order.shipping_postal_code, city=order.shipping_city, province=order.shipping_province,
            is_default=not Address.objects.filter(user=user).exists(),
        )
    messages.success(request, "Hemos guardado tu dirección y tu pedido en tu cuenta.")


def login_view(request):
    """The only way into an account by typing something: an email address.
    No password exists to register or reset — this sends a one-time code
    (see verify_login_code) and creates the account on first successful
    verification if it doesn't exist yet, exactly like Google sign-in does."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    next_url = _safe_next_url(request, request.POST.get("next") or request.GET.get("next")) or ""
    error = None
    email = request.session.get("login_code_email", "")

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            error = "Introduce un correo electrónico válido."
        else:
            sent = send_login_code(email)
            request.session["login_code_email"] = email
            if next_url:
                request.session["login_code_next"] = next_url
            else:
                request.session.pop("login_code_next", None)
            if not sent:
                messages.info(request, "Ya te hemos enviado un código hace un momento — revisa tu correo.")
            return redirect("accounts:verify_login_code")

    return render(request, "registration/login.html", {
        "error": error, "email": email, "next": next_url,
    })


@require_POST
def logout_view(request):
    auth_logout(request)
    return redirect("catalog:home")


def google_login(request):
    if not (settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET):
        messages.error(request, "El acceso con Google no está disponible en este momento.")
        return redirect("accounts:login")

    state = secrets.token_urlsafe(24)
    request.session["google_oauth_state"] = state

    next_url = _safe_next_url(request, request.GET.get("next"))
    if next_url:
        request.session["google_oauth_next"] = next_url
    else:
        request.session.pop("google_oauth_next", None)

    return redirect(build_authorization_url(request, state))


def google_callback(request):
    expected_state = request.session.pop("google_oauth_state", None)
    next_url = request.session.pop("google_oauth_next", None)

    if request.GET.get("error"):
        messages.info(request, "Acceso con Google cancelado.")
        return redirect("accounts:login")

    code = request.GET.get("code")
    state = request.GET.get("state")
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        messages.error(request, "No se ha podido verificar la solicitud de Google. Inténtalo de nuevo.")
        return redirect("accounts:login")

    try:
        profile = fetch_userinfo(request, code)
    except GoogleOAuthError:
        messages.error(request, "No se ha podido completar el acceso con Google. Inténtalo de nuevo.")
        return redirect("accounts:login")

    email = (profile.get("email") or "").strip().lower()
    if not email or not profile.get("email_verified"):
        messages.error(request, "Tu cuenta de Google debe tener un correo verificado para continuar.")
        return redirect("accounts:login")

    is_new = not User.objects.filter(username=email).exists()
    user = _get_or_create_user(email, profile.get("given_name", ""), profile.get("family_name", ""))
    if is_new:
        messages.success(request, f"¡Bienvenido/a, {user.first_name or email}! Tu cuenta se ha creado con Google.")

    auth_login(request, user)
    _claim_pending_order(request, user)
    return redirect(next_url or "accounts:dashboard")


def verify_login_code(request):
    email = request.session.get("login_code_email")
    if not email:
        return redirect("accounts:login")

    next_url = request.session.get("login_code_next") or ""
    error = None

    if request.method == "POST":
        submitted_code = request.POST.get("code", "").strip()
        login_code = LoginCode.objects.filter(email=email).order_by("-created_at").first()
        if login_code and login_code.verify(submitted_code):
            request.session.pop("login_code_email", None)
            request.session.pop("login_code_next", None)
            user = _get_or_create_user(email)
            auth_login(request, user)
            _claim_pending_order(request, user)
            return redirect(next_url or "accounts:dashboard")
        error = "Código incorrecto o caducado."

    return render(request, "registration/login_code_verify.html", {
        "email": email, "error": error, "next": next_url,
    })


@require_POST
def resend_login_code(request):
    email = request.session.get("login_code_email")
    if not email:
        return redirect("accounts:login")
    if send_login_code(email):
        messages.success(request, "Te hemos enviado un nuevo código.")
    else:
        messages.info(request, "Ya te hemos enviado un código hace un momento — revisa tu correo.")
    return redirect("accounts:verify_login_code")


@require_POST
def claim_order(request, token):
    """'Guardar mis datos' button on a paid guest order's status page."""
    from orders.models import Order
    order = get_object_or_404(Order, access_token=token, status=Order.Status.PAID)

    if order.user_id:
        messages.info(request, "Este pedido ya está asociado a una cuenta.")
        return redirect(order.get_status_url())

    if request.user.is_authenticated and request.user.email.lower() == order.email.lower():
        request.session["claim_order_token"] = str(order.access_token)
        _claim_pending_order(request, request.user)
        return redirect(order.get_status_url())

    sent = send_login_code(order.email)
    request.session["login_code_email"] = order.email
    request.session["login_code_next"] = order.get_status_url()
    request.session["claim_order_token"] = str(order.access_token)
    if not sent:
        messages.info(request, "Ya te hemos enviado un código hace un momento — revisa tu correo.")
    return redirect("accounts:verify_login_code")


@login_required
def dashboard(request):
    addresses = request.user.addresses.all()
    orders = request.user.orders.all()[:5]
    return render(request, "accounts/dashboard.html", {"addresses": addresses, "orders": orders})


@login_required
def address_list(request):
    addresses = request.user.addresses.all()
    return render(request, "accounts/address_list.html", {"addresses": addresses})


@login_required
def address_add(request):
    values = {}
    errors = {}
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if request.method == "POST":
        values = address_fields_from_post(request.POST)
        errors = validate_address(values)
        if not errors:
            Address.objects.create(user=request.user, **values)
            messages.success(request, "Dirección añadida.")
            return redirect(next_url or "accounts:address_list")
    return render(request, "accounts/address_form.html", {
        "errors": errors, "values": values, "is_edit": False, "next": next_url,
    })


@login_required
def address_edit(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    values = {**address_to_dict(address), "is_default": address.is_default}
    errors = {}
    if request.method == "POST":
        values = address_fields_from_post(request.POST)
        errors = validate_address(values)
        if not errors:
            for field, value in values.items():
                setattr(address, field, value)
            address.save()
            messages.success(request, "Dirección actualizada.")
            return redirect("accounts:address_list")
    return render(request, "accounts/address_form.html", {
        "errors": errors, "values": values, "is_edit": True, "address": address,
    })


@login_required
def address_delete(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == "POST":
        address.delete()
        messages.success(request, "Dirección eliminada.")
        return redirect("accounts:address_list")
    return render(request, "accounts/address_confirm_delete.html", {"address": address})


@login_required
def address_set_default(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == "POST":
        address.is_default = True
        address.save()
        messages.success(request, "Dirección predeterminada actualizada.")
    return redirect("accounts:address_list")
