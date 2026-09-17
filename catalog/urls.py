from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.home, name="home"),
    path("products/<slug:slug>/", views.product_detail, name="product_detail"),
]
