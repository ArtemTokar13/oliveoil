from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Product

from .models import CartItem
from .utils import get_cart


def _is_fetch(request):
    return request.headers.get("X-Requested-With") == "fetch"


def detail(request):
    current_cart = get_cart(request, create=False)
    items = current_cart.items.select_related("product").all() if current_cart else []
    return render(request, "cart/detail.html", {"cart": current_cart, "items": items})


@require_POST
def add(request):
    product = get_object_or_404(Product, pk=request.POST.get("product_id"), is_active=True)
    try:
        quantity = max(1, int(request.POST.get("quantity", 1)))
    except (TypeError, ValueError):
        quantity = 1

    current_cart = get_cart(request)
    item, created = CartItem.objects.get_or_create(
        cart=current_cart, product=product, defaults={"quantity": quantity},
    )
    if not created:
        item.quantity = min(item.quantity + quantity, product.stock or item.quantity + quantity)
        item.save(update_fields=["quantity"])

    if _is_fetch(request):
        return JsonResponse({
            "ok": True,
            "cart_items_count": current_cart.items_count,
            "message": f"{product.name} añadido al carrito.",
        })

    messages.success(request, f"{product.name} añadido al carrito.")
    return redirect(request.POST.get("next") or product.get_absolute_url())


@require_POST
def update(request, item_id):
    current_cart = get_cart(request, create=False)
    item = get_object_or_404(CartItem, pk=item_id, cart=current_cart)
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = item.quantity

    if quantity < 1:
        item.delete()
    else:
        item.quantity = min(quantity, item.product.stock) if item.product.stock else quantity
        item.save(update_fields=["quantity"])

    return redirect("cart:detail")


@require_POST
def remove(request, item_id):
    current_cart = get_cart(request, create=False)
    item = get_object_or_404(CartItem, pk=item_id, cart=current_cart)
    item.delete()
    messages.success(request, "Producto eliminado del carrito.")
    return redirect("cart:detail")
