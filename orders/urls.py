from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("buy-now/", views.buy_now, name="buy_now"),
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/cancelled/", views.checkout_cancel, name="checkout_cancel"),
    path("orders/", views.order_list, name="list"),
    path("orders/<int:pk>/", views.order_detail, name="detail"),
    path("orders/status/<uuid:token>/", views.order_status, name="status"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
