from django.conf import settings


def site(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_LEGAL_NAME": settings.SITE_LEGAL_NAME,
        "SITE_NIF": settings.SITE_NIF,
        "SITE_ADDRESS": settings.SITE_ADDRESS,
        "SITE_EMAIL": settings.SITE_EMAIL,
        "SITE_PHONE": settings.SITE_PHONE,
        "SITE_IAE": settings.SITE_IAE,
        "STRIPE_PUBLISHABLE_KEY": settings.STRIPE_PUBLISHABLE_KEY,
        "GOOGLE_OAUTH_ENABLED": bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET),
    }
