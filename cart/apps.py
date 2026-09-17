from django.apps import AppConfig


class CartConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cart"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .utils import merge_session_cart_into_user

        def _merge_on_login(sender, request, user, **kwargs):
            merge_session_cart_into_user(request, user)

        user_logged_in.connect(_merge_on_login, dispatch_uid="cart_merge_on_login")
