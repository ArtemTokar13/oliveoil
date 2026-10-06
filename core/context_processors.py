from django.conf import settings


# Apps whose pages are private or transactional — kept out of search results.
NOINDEX_APPS = {"cart", "orders", "accounts"}


def site(request):
    match = getattr(request, "resolver_match", None)
    return {
        "SITE_URL": settings.SITE_URL,
        "NOINDEX": bool(match and match.app_name in NOINDEX_APPS),
        "SITE_NAME": settings.SITE_NAME,
        "SITE_LEGAL_NAME": settings.SITE_LEGAL_NAME,
        "SITE_NIF": settings.SITE_NIF,
        "SITE_ADDRESS": settings.SITE_ADDRESS,
        "SITE_EMAIL": settings.SITE_EMAIL,
        "SITE_PHONE": settings.SITE_PHONE,
        "SITE_IAE": settings.SITE_IAE,
        "STRIPE_PUBLISHABLE_KEY": settings.STRIPE_PUBLISHABLE_KEY,
        "GA_MEASUREMENT_ID": settings.GA_MEASUREMENT_ID,
        "GOOGLE_OAUTH_ENABLED": bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET),
    }
