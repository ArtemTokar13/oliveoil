from django.conf import settings
from django.http import HttpResponsePermanentRedirect


class CanonicalHostMiddleware:
    """301 www.* and legacy domains (olivarium.es) -> SITE_URL so search engines
    see a single site instead of identical copies."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0].lower()
        if host.startswith("www.") or host in settings.LEGACY_HOSTS:
            return HttpResponsePermanentRedirect(f"{settings.SITE_URL}{request.get_full_path()}")
        return self.get_response(request)
