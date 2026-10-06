"""schema.org structured data (JSON-LD) for search engines — lets Google show
price/availability in results and list products for free in the Shopping
tab (Google Merchant Center can read them straight from the page)."""

from django.conf import settings
from django.urls import reverse

from orders.models import ShippingSettings

# Shipping-and-returns page: "2 a 5 días laborables desde la confirmación del
# pago", "14 días naturales ... para solicitar su devolución".
HANDLING_DAYS = (0, 1)
TRANSIT_DAYS = (2, 4)
RETURN_DAYS = 14


def absolute(path):
    return f"{settings.SITE_URL}{path}"


def _days(min_value, max_value):
    return {"@type": "QuantitativeValue", "minValue": min_value, "maxValue": max_value, "unitCode": "DAY"}


def product_structured_data(product):
    url = absolute(product.get_absolute_url())
    shipping = ShippingSettings.get_solo()
    threshold = shipping.free_shipping_threshold
    shipping_fee = 0 if threshold is not None and product.price >= threshold else shipping.flat_fee

    description = product.description.strip() or f"{product.name}, {product.get_volume_display()}."
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": f"{product.name} ({product.get_volume_display()})",
        "description": description,
        "sku": product.slug,
        "url": url,
        "image": [absolute(image.image.url) for image in product.images.all()],
        "category": product.category.name,
        "offers": {
            "@type": "Offer",
            "url": url,
            "priceCurrency": "EUR",
            "price": str(product.price),
            "availability": "https://schema.org/InStock" if product.in_stock else "https://schema.org/OutOfStock",
            "itemCondition": "https://schema.org/NewCondition",
            "seller": {"@type": "Organization", "name": settings.SITE_NAME},
            "shippingDetails": {
                "@type": "OfferShippingDetails",
                "shippingRate": {"@type": "MonetaryAmount", "value": str(shipping_fee), "currency": "EUR"},
                "shippingDestination": {"@type": "DefinedRegion", "addressCountry": "ES"},
                "deliveryTime": {
                    "@type": "ShippingDeliveryTime",
                    "handlingTime": _days(*HANDLING_DAYS),
                    "transitTime": _days(*TRANSIT_DAYS),
                },
            },
            "hasMerchantReturnPolicy": {
                "@type": "MerchantReturnPolicy",
                "applicableCountry": "ES",
                "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow",
                "merchantReturnDays": RETURN_DAYS,
                "returnMethod": "https://schema.org/ReturnByMail",
                "returnFees": "https://schema.org/ReturnFeesCustomerResponsibility",
            },
        },
    }
    if product.brand:
        data["brand"] = {"@type": "Brand", "name": product.brand.name}
    if not data["image"]:
        del data["image"]

    breadcrumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Tienda", "item": absolute(reverse("catalog:home"))},
            {"@type": "ListItem", "position": 2, "name": product.name, "item": url},
        ],
    }
    return [data, breadcrumbs]


def store_structured_data():
    home = absolute(reverse("catalog:home"))
    return [
        {
            "@context": "https://schema.org",
            "@type": "OnlineStore",
            "name": settings.SITE_NAME,
            "url": home,
            "email": settings.SITE_EMAIL,
            "telephone": settings.SITE_PHONE,
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Castellón de la Plana",
                "addressRegion": "Castellón",
                "addressCountry": "ES",
            },
            "areaServed": "ES",
        },
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": settings.SITE_NAME,
            "url": home,
            "inLanguage": "es-ES",
        },
    ]
