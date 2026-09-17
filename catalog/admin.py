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


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "thumbnail", "name", "brand", "category", "volume",
        "price", "stock", "is_active", "harvest_year",
    )
    list_display_links = ("thumbnail", "name")
    list_filter = ("brand", "category", "volume", "is_active")
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
