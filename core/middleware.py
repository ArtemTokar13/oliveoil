from django.conf import settings
from django.http import HttpResponsePermanentRedirect


class CanonicalHostMiddleware:
    """301 www.olivarium.es/... -> olivarium.es/... so search engines see a
    single site instead of two identical copies."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.get_host().startswith("www."):
            return HttpResponsePermanentRedirect(f"{settings.SITE_URL}{request.get_full_path()}")
        return self.get_response(request)
