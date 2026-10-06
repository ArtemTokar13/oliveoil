from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from catalog.models import Product


class ProductSitemap(Sitemap):
    protocol = "https"
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Product.objects.filter(is_active=True).order_by("pk")

    def lastmod(self, product):
        return product.updated_at


class StaticPageSitemap(Sitemap):
    protocol = "https"
    changefreq = "monthly"

    PAGES = {
        "catalog:home": 1.0,
        "pages:about": 0.5,
        "pages:contact": 0.4,
        "pages:shipping_returns": 0.4,
        "pages:terms_of_sale": 0.2,
        "pages:legal_notice": 0.1,
        "pages:privacy_policy": 0.1,
        "pages:cookie_policy": 0.1,
    }

    def items(self):
        return list(self.PAGES)

    def location(self, name):
        return reverse(name)

    def priority(self, name):
        return self.PAGES[name]


SITEMAPS = {"products": ProductSitemap, "pages": StaticPageSitemap}
