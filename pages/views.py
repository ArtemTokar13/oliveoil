from django.contrib import messages
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.conf import settings
from django.shortcuts import redirect, render

from .models import ContactMessage


def about(request):
    return render(request, "pages/about.html")


def legal_notice(request):
    return render(request, "pages/legal_notice.html")


def privacy_policy(request):
    return render(request, "pages/privacy_policy.html")


def cookie_policy(request):
    return render(request, "pages/cookie_policy.html")


def terms_of_sale(request):
    return render(request, "pages/terms_of_sale.html")


def shipping_returns(request):
    from orders.models import ShippingSettings
    return render(request, "pages/shipping_returns.html", {"shipping": ShippingSettings.get_solo()})


def contact(request):
    errors = {}
    values = {"name": "", "email": "", "subject": "", "message": ""}

    if request.method == "POST":
        values = {
            "name": request.POST.get("name", "").strip(),
            "email": request.POST.get("email", "").strip(),
            "subject": request.POST.get("subject", "").strip(),
            "message": request.POST.get("message", "").strip(),
        }
        if not values["name"]:
            errors["name"] = "Introduce tu nombre."
        try:
            validate_email(values["email"])
        except ValidationError:
            errors["email"] = "Introduce un correo electrónico válido."
        if not values["subject"]:
            errors["subject"] = "Introduce un asunto."
        if not values["message"]:
            errors["message"] = "Escribe tu mensaje."
        if not request.POST.get("privacy_consent"):
            errors["privacy_consent"] = "Debes aceptar la política de privacidad para enviar el mensaje."

        if not errors:
            ContactMessage.objects.create(**values)
            try:
                EmailMessage(
                    subject=f"[Contacto] {values['subject']}",
                    body=f"De: {values['name']} <{values['email']}>\n\n{values['message']}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[settings.CONTACT_EMAIL],
                    # So "Reply" in the inbox goes straight to the visitor.
                    reply_to=[values["email"]],
                ).send(fail_silently=True)
            except Exception:
                pass
            messages.success(request, "Gracias por tu mensaje. Te responderemos lo antes posible.")
            return redirect("pages:contact")

    return render(request, "pages/contact.html", {"errors": errors, "values": values})
