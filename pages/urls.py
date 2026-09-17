from django.urls import path

from . import views

app_name = "pages"

urlpatterns = [
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("legal-notice/", views.legal_notice, name="legal_notice"),
    path("privacy-policy/", views.privacy_policy, name="privacy_policy"),
    path("cookie-policy/", views.cookie_policy, name="cookie_policy"),
    path("terms-of-sale/", views.terms_of_sale, name="terms_of_sale"),
    path("shipping-returns/", views.shipping_returns, name="shipping_returns"),
]
