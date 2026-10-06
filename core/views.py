from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

# Private/transactional pages: nothing for a search engine there. They also
# carry <meta name="robots" content="noindex"> (see core.context_processors).
DISALLOWED_PATHS = ["/admin/", "/cart/", "/checkout/", "/buy-now/", "/orders/", "/account/", "/login/", "/logout/"]


@require_GET
@cache_control(max_age=86400, public=True)
def robots_txt(request):
    lines = ["User-agent: *"]
    lines += [f"Disallow: {path}" for path in DISALLOWED_PATHS]
    lines += ["", f"Sitemap: {settings.SITE_URL}/sitemap.xml", ""]
    return HttpResponse("\n".join(lines), content_type="text/plain")
