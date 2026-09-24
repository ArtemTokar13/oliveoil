from django.contrib import admin

from .models import Order, OrderItem, ShippingSettings


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "product_volume", "unit_price", "quantity", "line_total")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Total línea")
    def line_total(self, obj):
        return obj.line_total


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id", "customer", "status", "fulfillment_status", "total",
        "is_local_delivery", "local_delivery_date", "created_at", "paid_at",
    )
    list_filter = ("status", "fulfillment_status", "is_local_delivery", "created_at")
    search_fields = ("id", "email", "user__email", "shipping_full_name", "stripe_checkout_session_id")
    readonly_fields = (
        "user", "email", "session_key", "access_token", "subtotal", "shipping_cost", "total",
        "is_local_delivery", "local_delivery_date",
        "stripe_checkout_session_id", "stripe_payment_intent_id", "created_at", "updated_at", "paid_at",
    )
    inlines = [OrderItemInline]
    date_hierarchy = "created_at"

    @admin.display(description="Cliente", ordering="email")
    def customer(self, obj):
        if obj.user:
            return f"{obj.user} (cuenta)"
        return f"{obj.email} (invitado)"


@admin.register(ShippingSettings)
class ShippingSettingsAdmin(admin.ModelAdmin):
    list_display = ("flat_fee", "free_shipping_threshold", "local_delivery_weekday")

    def has_add_permission(self, request):
        return not ShippingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
