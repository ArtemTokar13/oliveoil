from .models import Cart


def get_cart(request, create=True):
    """Return the Cart for the current visitor (session-based when anonymous,
    user-linked when authenticated), creating one if needed."""
    if request.user.is_authenticated:
        if create:
            cart, _ = Cart.objects.get_or_create(user=request.user)
            return cart
        return Cart.objects.filter(user=request.user).first()

    if not request.session.session_key:
        if not create:
            return None
        request.session.save()

    session_key = request.session.session_key
    if not session_key:
        return None

    if create:
        cart, _ = Cart.objects.get_or_create(session_key=session_key)
        return cart
    return Cart.objects.filter(session_key=session_key).first()


def merge_session_cart_into_user(request, user):
    """Fold an anonymous session cart into the logged-in user's cart."""
    session_key = request.session.session_key
    if not session_key:
        return

    anon_cart = Cart.objects.filter(session_key=session_key).first()
    if not anon_cart:
        return

    user_cart, _ = Cart.objects.get_or_create(user=user)

    for item in anon_cart.items.all():
        existing = user_cart.items.filter(product=item.product).first()
        if existing:
            existing.quantity += item.quantity
            existing.save(update_fields=["quantity"])
        else:
            item.cart = user_cart
            item.save(update_fields=["cart"])

    anon_cart.delete()
