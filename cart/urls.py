from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.detail, name="detail"),
    path("add/", views.add, name="add"),
    path("update/<int:item_id>/", views.update, name="update"),
    path("remove/<int:item_id>/", views.remove, name="remove"),
]
