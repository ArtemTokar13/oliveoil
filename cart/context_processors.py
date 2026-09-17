from .utils import get_cart


def cart(request):
    current_cart = get_cart(request, create=False)
    return {
        "cart_items_count": current_cart.items_count if current_cart else 0,
        "mini_cart": current_cart,
    }
