from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import Brand, Category, Product

PAGE_SIZE = 12


def home(request):
    products = (
        Product.objects.filter(is_active=True)
        .select_related("brand", "category")
        .prefetch_related("images")
    )

    category_slug = request.GET.get("categoria")
    brand_slug = request.GET.get("marca")

    if category_slug:
        products = products.filter(category__slug=category_slug)
    if brand_slug:
        products = products.filter(brand__slug=brand_slug)

    paginator = Paginator(products, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "products": page_obj.object_list,
        "categories": Category.objects.all(),
        "brands": Brand.objects.all(),
        "selected_category": category_slug,
        "selected_brand": brand_slug,
    }
    return render(request, "catalog/home.html", context)


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("brand", "category").prefetch_related("images"),
        slug=slug, is_active=True,
    )
    related = (
        Product.objects.filter(category=product.category, is_active=True)
        .exclude(pk=product.pk)
        .select_related("brand")[:4]
    )
    return render(request, "catalog/product_detail.html", {"product": product, "related": related})
