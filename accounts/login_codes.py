from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import LoginCode


def send_login_code(email):
    """Issue a fresh code and email it, unless one was just sent (cooldown).
    Returns True if a code went out, False if we're within the cooldown."""
    if LoginCode.cooldown_active(email):
        return False

    _login_code, code = LoginCode.issue(email)
    body = render_to_string("registration/login_code_email.txt", {
        "code": code, "SITE_NAME": settings.SITE_NAME,
        "valid_minutes": LoginCode.VALID_MINUTES,
    })
    send_mail(
        subject=f"Tu código de acceso a {settings.SITE_NAME}",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )
    return True
