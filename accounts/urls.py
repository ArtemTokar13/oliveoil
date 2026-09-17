from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/google/", views.google_login, name="google_login"),
    path("login/google/callback/", views.google_callback, name="google_callback"),
    path("login/code/verify/", views.verify_login_code, name="verify_login_code"),
    path("login/code/resend/", views.resend_login_code, name="resend_login_code"),
    path("orders/<uuid:token>/claim/", views.claim_order, name="claim_order"),
    path("logout/", views.logout_view, name="logout"),
    path("account/", views.dashboard, name="dashboard"),
    path("account/addresses/", views.address_list, name="address_list"),
    path("account/addresses/new/", views.address_add, name="address_add"),
    path("account/addresses/<int:pk>/edit/", views.address_edit, name="address_edit"),
    path("account/addresses/<int:pk>/delete/", views.address_delete, name="address_delete"),
    path("account/addresses/<int:pk>/default/", views.address_set_default, name="address_set_default"),
]
