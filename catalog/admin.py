from django.contrib import admin
from django.utils.html import format_html

from .models import Brand, Category, Product, ProductImage


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "product_count", "logo_preview")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Productos")
    def product_count(self, obj):
        return obj.products.count()

    @admin.display(description="Logo")
    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" style="height:32px;border-radius:4px;">', obj.logo.url)
        return "—"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "product_count")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Productos")
    def product_count(self, obj):
        return obj.products.count()


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("image", "preview", "alt_text", "order")
    readonly_fields = ("preview",)

    @admin.display(description="Vista previa")
    def preview(self, obj):
        if obj.pk and obj.image:
            return format_html('<img src="{}" style="height:60px;border-radius:4px;">', obj.image.url)
        return "—"


class StockFilter(admin.SimpleListFilter):
    title = "stock"
    parameter_name = "stock_level"

    def lookups(self, request, model_admin):
        return [("out", "Agotado"), ("low", "Stock bajo (1–3)"), ("ok", "Con stock (4+)")]

    def queryset(self, request, queryset):
        if self.value() == "out":
            return queryset.filter(stock=0)
        if self.value() == "low":
            return queryset.filter(stock__gte=1, stock__lte=3)
        if self.value() == "ok":
            return queryset.filter(stock__gte=4)
        return queryset


@admin.action(description="Mostrar en la tienda")
def make_active(modeladmin, request, queryset):
    updated = queryset.update(is_active=True)
    modeladmin.message_user(request, f"{updated} producto(s) visibles en la tienda.")


@admin.action(description="Ocultar de la tienda")
def make_inactive(modeladmin, request, queryset):
    updated = queryset.update(is_active=False)
    modeladmin.message_user(request, f"{updated} producto(s) ocultos de la tienda.")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "thumbnail", "name", "brand", "category", "volume",
        "price", "stock", "is_active", "harvest_year",
    )
    list_display_links = ("thumbnail", "name")
    list_filter = ("is_active", StockFilter, "brand", "category", "volume")
    actions = [make_active, make_inactive]
    search_fields = ("name", "brand__name", "origin_region")
    list_editable = ("price", "stock", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("brand",)
    inlines = [ProductImageInline]
    fieldsets = (
        (None, {"fields": ("name", "slug", "brand", "category", "is_active")}),
        ("Detalles del producto", {
            "fields": ("volume", "origin_region", "harvest_year", "acidity", "description"),
        }),
        ("Precio y stock", {"fields": ("price", "stock")}),
    )

    @admin.display(description="")
    def thumbnail(self, obj):
        image = obj.main_image
        if image:
            return format_html('<img src="{}" style="height:40px;width:40px;object-fit:cover;border-radius:4px;">', image.image.url)
        return "—"


admin.site.site_header = "Olivarium — Administración"
admin.site.site_title = "Olivarium"
admin.site.index_title = "Panel de gestión"
