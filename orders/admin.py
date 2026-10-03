from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html

from .models import Customer, DiscountCode, Order, OrderItem, ShippingSettings
from .services import send_status_update_email
from .stats import customer_rows, customer_summary


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


def _set_fulfillment_status(modeladmin, request, queryset, new_status):
    """Bulk action body: only paid orders have a shipping state worth moving,
    and every order that actually changes gets the customer email."""
    changed = emailed = skipped = 0
    for order in queryset:
        if order.status != Order.Status.PAID:
            skipped += 1
            continue
        if order.fulfillment_status == new_status:
            continue
        order.fulfillment_status = new_status
        order.save(update_fields=["fulfillment_status", "updated_at"])
        changed += 1
        if send_status_update_email(request, order):
            emailed += 1
    label = Order.FulfillmentStatus(new_status).label
    modeladmin.message_user(
        request,
        f"{changed} pedido(s) marcados como «{label}»; {emailed} correo(s) enviados al cliente.",
        messages.SUCCESS,
    )
    if skipped:
        modeladmin.message_user(
            request, f"{skipped} pedido(s) omitidos porque no están pagados.", messages.WARNING,
        )


@admin.action(description="Marcar como «En preparación» y avisar al cliente")
def mark_processing(modeladmin, request, queryset):
    _set_fulfillment_status(modeladmin, request, queryset, Order.FulfillmentStatus.PROCESSING)


@admin.action(description="Marcar como «Enviado» y avisar al cliente")
def mark_shipped(modeladmin, request, queryset):
    _set_fulfillment_status(modeladmin, request, queryset, Order.FulfillmentStatus.SHIPPED)


@admin.action(description="Marcar como «Entregado» y avisar al cliente")
def mark_delivered(modeladmin, request, queryset):
    _set_fulfillment_status(modeladmin, request, queryset, Order.FulfillmentStatus.DELIVERED)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number", "customer", "status", "fulfillment_status", "total",
        "is_local_delivery", "local_delivery_date", "created_at", "paid_at",
    )
    list_display_links = ("number", "customer")
    list_filter = ("status", "fulfillment_status", "is_local_delivery", "created_at")
    search_fields = ("email", "user__email", "shipping_full_name", "shipping_phone", "stripe_checkout_session_id")
    search_help_text = "Busca por nº de pedido (p. ej. 9EB54), correo, nombre o teléfono."
    readonly_fields = (
        "number", "user", "email", "session_key", "access_token", "status_page",
        "subtotal", "discount_code", "discount_amount", "shipping_cost", "total",
        "is_local_delivery", "local_delivery_date",
        "stripe_checkout_session_id", "stripe_payment_intent_id", "created_at", "updated_at", "paid_at",
    )
    fieldsets = (
        ("Estado", {
            "fields": ("number", "status", "fulfillment_status", "tracking_number", "tracking_url"),
            "description": (
                "Al cambiar el estado de envío de un pedido pagado (En preparación, Enviado, "
                "Entregado) se envía automáticamente un correo al cliente."
            ),
        }),
        ("Cliente", {"fields": ("user", "email", "status_page")}),
        ("Dirección de envío", {"fields": (
            "shipping_full_name", "shipping_phone", "shipping_street_address", "shipping_apartment",
            "shipping_postal_code", "shipping_city", "shipping_province", "shipping_country",
            "is_local_delivery", "local_delivery_date",
        )}),
        ("Importes", {"fields": ("subtotal", "discount_code", "discount_amount", "shipping_cost", "total")}),
        ("Pago (Stripe)", {
            "classes": ("collapse",),
            "fields": (
                "stripe_checkout_session_id", "stripe_payment_intent_id", "session_key", "access_token",
                "created_at", "updated_at", "paid_at",
            ),
        }),
    )
    inlines = [OrderItemInline]
    actions = [mark_processing, mark_shipped, mark_delivered]
    date_hierarchy = "created_at"
    list_select_related = ("user",)

    @admin.display(description="Pedido", ordering="created_at")
    def number(self, obj):
        return f"#{obj.order_number}"

    @admin.display(description="Cliente", ordering="email")
    def customer(self, obj):
        if obj.user:
            return f"{obj.user} (cuenta)"
        return f"{obj.email} (invitado)"

    @admin.display(description="Página del pedido")
    def status_page(self, obj):
        if not obj.pk:
            return "—"
        return format_html('<a href="{}" target="_blank">Ver como el cliente</a>', obj.get_status_url())

    def get_search_results(self, request, queryset, search_term):
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        # The public order number is the first 5 hex chars of access_token.
        term = search_term.strip().lstrip("#").lower()
        if len(term) == 5 and all(c in "0123456789abcdef" for c in term):
            queryset |= self.model.objects.filter(access_token__startswith=term)
        return queryset, may_have_duplicates

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and "fulfillment_status" in form.changed_data:
            if obj.status != Order.Status.PAID:
                self.message_user(
                    request, "El pedido no está pagado: no se ha enviado ningún correo al cliente.",
                    messages.WARNING,
                )
            elif send_status_update_email(request, obj):
                self.message_user(
                    request, f"Se ha enviado un correo a {obj.email} con el nuevo estado del pedido.",
                    messages.SUCCESS,
                )
            elif obj.fulfillment_status != Order.FulfillmentStatus.RECEIVED:
                self.message_user(
                    request, "No se ha podido enviar el correo al cliente (revisa logs/errors.log).",
                    messages.ERROR,
                )


class DiscountStatusFilter(admin.SimpleListFilter):
    title = "estado"
    parameter_name = "estado"

    def lookups(self, request, model_admin):
        return [("active", "Activo"), ("used", "Usado"), ("expired", "Caducado sin usar")]

    def queryset(self, request, queryset):
        from django.utils import timezone
        now = timezone.now()
        if self.value() == "active":
            return queryset.filter(used_at__isnull=True, expires_at__gt=now)
        if self.value() == "used":
            return queryset.filter(used_at__isnull=False)
        if self.value() == "expired":
            return queryset.filter(used_at__isnull=True, expires_at__lte=now)
        return queryset


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "email", "percent", "state", "expires_at", "issued_for", "used_in", "created_at")
    list_filter = (DiscountStatusFilter,)
    search_fields = ("code", "email")
    readonly_fields = ("issued_for_order", "used_at", "created_at", "used_in")
    fields = ("code", "email", "percent", "expires_at", "issued_for_order", "used_at", "used_in", "created_at")

    @admin.display(description="Estado")
    def state(self, obj):
        if obj.is_used:
            return "✅ Usado"
        if obj.is_expired:
            return "⌛ Caducado"
        return "🟢 Activo"

    @admin.display(description="Emitido por")
    def issued_for(self, obj):
        if not obj.issued_for_order_id:
            return "Manual"
        url = reverse("admin:orders_order_change", args=[obj.issued_for_order_id])
        return format_html('<a href="{}">#{}</a>', url, obj.issued_for_order.order_number)

    @admin.display(description="Usado en")
    def used_in(self, obj):
        order = obj.orders.filter(status=Order.Status.PAID).first()
        if not order:
            return "—"
        url = reverse("admin:orders_order_change", args=[order.pk])
        return format_html('<a href="{}">#{}</a>', url, order.order_number)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """Read-only, aggregated customer list — one row per email across
    registered accounts and guest orders."""

    SORTS = {
        "spent": ("total_spent", "Total gastado"),
        "orders": ("order_count", "Nº de pedidos"),
        "last": ("last_order", "Último pedido"),
        "first": ("first_order", "Primer pedido"),
    }

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        query = request.GET.get("q", "").strip()
        sort = request.GET.get("o", "spent")
        if sort not in self.SORTS:
            sort = "spent"

        rows = customer_rows()
        summary = customer_summary(rows)
        if query:
            q = query.lower()
            rows = [r for r in rows if q in r["email"] or q in (r["name"] or "").lower() or q in (r["phone"] or "")]
        key = self.SORTS[sort][0]
        rows.sort(key=lambda r: (r[key] is not None, r[key] or 0), reverse=True)

        orders_url = reverse("admin:orders_order_changelist")
        for row in rows:
            row["orders_url"] = f"{orders_url}?q={row['email']}"

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Clientes",
            "rows": rows,
            "summary": summary,
            "query": query,
            "sort": sort,
            "sorts": [(k, v[1]) for k, v in self.SORTS.items()],
            **(extra_context or {}),
        }
        return TemplateResponse(request, "admin/orders/customer/change_list.html", context)


@admin.register(ShippingSettings)
class ShippingSettingsAdmin(admin.ModelAdmin):
    list_display = ("flat_fee", "free_shipping_threshold", "local_delivery_weekday")

    def has_add_permission(self, request):
        return not ShippingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
