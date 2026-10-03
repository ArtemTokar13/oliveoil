"""Numbers for the admin: the customer list and the dashboard on the admin
index. Volumes are small, so plain aggregate queries + a bit of Python are
plenty — no caching."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Max, Min, Sum
from django.db.models.functions import Lower
from django.utils import timezone

from catalog.models import Product

from .models import DiscountCode, Order, OrderItem

LOW_STOCK_THRESHOLD = 3


def customer_rows():
    """One dict per customer email: everyone who has paid for an order
    (guest or account) plus registered accounts that haven't bought yet."""
    paid = Order.objects.filter(status=Order.Status.PAID).exclude(email="")
    aggregates = (
        paid.annotate(email_lc=Lower("email"))
        .values("email_lc")
        .annotate(
            order_count=Count("id"),
            total_spent=Sum("total"),
            first_order=Min("paid_at"),
            last_order=Max("paid_at"),
        )
    )
    # Latest name/phone per email — the order list is newest first, so the
    # first one seen for each email wins.
    latest = {}
    for email, name, phone in paid.order_by("-paid_at").values_list("email", "shipping_full_name", "shipping_phone"):
        latest.setdefault(email.lower(), (name, phone))

    users = {
        u.email.lower(): u
        for u in get_user_model().objects.filter(is_staff=False).exclude(email="")
    }
    active_codes = set(
        DiscountCode.objects.filter(used_at__isnull=True, expires_at__gt=timezone.now())
        .values_list("email", flat=True)
    )

    rows = []
    for agg in aggregates:
        email = agg["email_lc"]
        name, phone = latest.get(email, ("", ""))
        rows.append({
            "email": email,
            "name": name,
            "phone": phone,
            "has_account": email in users,
            "order_count": agg["order_count"],
            "total_spent": agg["total_spent"] or Decimal("0"),
            "avg_order": (agg["total_spent"] or Decimal("0")) / agg["order_count"],
            "first_order": agg["first_order"],
            "last_order": agg["last_order"],
            "has_active_code": email in active_codes,
        })

    buyers = {row["email"] for row in rows}
    for email, user in users.items():
        if email in buyers:
            continue
        rows.append({
            "email": email,
            "name": user.get_full_name(),
            "phone": "",
            "has_account": True,
            "order_count": 0,
            "total_spent": Decimal("0"),
            "avg_order": None,
            "first_order": None,
            "last_order": None,
            "has_active_code": email in active_codes,
        })
    return rows


def customer_summary(rows):
    buyers = [r for r in rows if r["order_count"]]
    repeat = [r for r in buyers if r["order_count"] >= 2]
    revenue = sum((r["total_spent"] for r in buyers), Decimal("0"))
    order_count = sum(r["order_count"] for r in buyers)
    return {
        "total": len(rows),
        "buyers": len(buyers),
        "accounts": sum(1 for r in rows if r["has_account"]),
        "repeat": len(repeat),
        "repeat_rate": round(100 * len(repeat) / len(buyers)) if buyers else 0,
        "revenue": revenue,
        "avg_order": revenue / order_count if order_count else Decimal("0"),
    }


def _period(paid, since):
    agg = paid.filter(paid_at__gte=since).aggregate(count=Count("id"), revenue=Sum("total"))
    return {"count": agg["count"], "revenue": agg["revenue"] or Decimal("0")}


def dashboard_stats():
    now = timezone.now()
    today_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    paid = Order.objects.filter(status=Order.Status.PAID)

    to_process = paid.filter(
        fulfillment_status__in=[Order.FulfillmentStatus.RECEIVED, Order.FulfillmentStatus.PROCESSING],
    )
    local_upcoming = (
        to_process.filter(is_local_delivery=True)
        .values("local_delivery_date")
        .annotate(count=Count("id"))
        .order_by("local_delivery_date")
    )

    top_products = (
        OrderItem.objects.filter(order__status=Order.Status.PAID, order__paid_at__gte=now - timedelta(days=30))
        .values("product_name", "product_volume")
        .annotate(units=Sum("quantity"), revenue=Sum(F("quantity") * F("unit_price")))
        .order_by("-units")[:5]
    )

    codes = DiscountCode.objects.all()
    issued = codes.filter(issued_for_order__isnull=False).count()
    used = codes.filter(issued_for_order__isnull=False, used_at__isnull=False).count()

    return {
        "periods": [
            ("Hoy", _period(paid, today_start)),
            ("Últimos 7 días", _period(paid, now - timedelta(days=7))),
            ("Este mes", _period(paid, month_start)),
            ("Últimos 30 días", _period(paid, now - timedelta(days=30))),
        ],
        "received": to_process.filter(fulfillment_status=Order.FulfillmentStatus.RECEIVED).count(),
        "processing": to_process.filter(fulfillment_status=Order.FulfillmentStatus.PROCESSING).count(),
        "shipped": paid.filter(fulfillment_status=Order.FulfillmentStatus.SHIPPED).count(),
        "abandoned_7d": Order.objects.filter(
            status__in=[Order.Status.PENDING, Order.Status.CANCELLED], created_at__gte=now - timedelta(days=7),
        ).count(),
        "local_upcoming": list(local_upcoming),
        "low_stock": list(
            Product.objects.filter(is_active=True, stock__lte=LOW_STOCK_THRESHOLD).order_by("stock", "name")
        ),
        "low_stock_threshold": LOW_STOCK_THRESHOLD,
        "top_products": list(top_products),
        "loyalty": {
            "issued": issued,
            "used": used,
            "rate": round(100 * used / issued) if issued else 0,
            "discount_total": paid.aggregate(s=Sum("discount_amount"))["s"] or Decimal("0"),
        },
    }
