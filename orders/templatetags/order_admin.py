from django import template

from orders.stats import dashboard_stats

register = template.Library()


@register.simple_tag
def admin_dashboard_stats():
    return dashboard_stats()
